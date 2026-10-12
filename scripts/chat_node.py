#!/usr/bin/env python3

import json
import queue
import threading
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import rospy
import yaml
from std_msgs.msg import Empty, String


class BailianChatNode:
    def __init__(self):
        config_file = Path(rospy.get_param("~config_file")).expanduser()
        with config_file.open(encoding="utf-8") as stream:
            config = yaml.safe_load(stream) or {}

        self.model = config.get("model", "qwen3.8-flash")
        self.base_url = config.get(
            "base_url", "https://dashscope.aliyuncs.com/compatible-mode/v1"
        ).rstrip("/")
        self.api_key = str(config.get("api_key", "")).strip()
        self.timeout = float(config.get("request_timeout_seconds", 30.0))
        self.max_tokens = int(config.get("max_tokens", 256))
        self.temperature = float(config.get("temperature", 0.7))
        self.max_history_turns = max(0, int(config.get("max_history_turns", 4)))
        max_queue_size = max(1, int(config.get("max_queue_size", 5)))
        self.system_prompt = config.get(
            "system_prompt", "请使用简洁、自然的中文回答。"
        )

        self.reply_pub = rospy.Publisher(
            "/spark_chat/reply_text", String, queue_size=10
        )
        self.status_pub = rospy.Publisher(
            "/spark_chat/status", String, queue_size=10
        )
        self.request_queue = queue.Queue(maxsize=max_queue_size)
        self.history = []

        rospy.Subscriber(
            "/spark_chat/user_text", String, self._on_user_text, queue_size=10
        )
        rospy.Subscriber(
            "/spark_chat/reset", Empty, self._on_reset, queue_size=1
        )

        worker = threading.Thread(target=self._worker, name="bailian-chat-worker")
        worker.daemon = True
        worker.start()
        self._publish_status("ready")
        rospy.loginfo("Bailian chat node ready; model=%s", self.model)

    def _publish_status(self, status):
        self.status_pub.publish(String(data=status))

    def _on_user_text(self, message):
        text = message.data.strip()
        if not text:
            return
        try:
            self.request_queue.put_nowait(("chat", text))
        except queue.Full:
            rospy.logwarn("Chat request queue is full; dropping an input")
            self._publish_status("busy")

    def _on_reset(self, _message):
        try:
            self.request_queue.put_nowait(("reset", None))
        except queue.Full:
            rospy.logwarn("Cannot queue conversation reset because the queue is full")
            self._publish_status("busy")

    def _worker(self):
        while not rospy.is_shutdown():
            try:
                action, payload = self.request_queue.get(timeout=0.2)
            except queue.Empty:
                continue

            if action == "reset":
                self.history = []
                self._publish_status("history_cleared")
                rospy.loginfo("Chat history cleared")
                continue

            self._handle_text(payload)

    def _handle_text(self, text):
        if not self.api_key:
            self._publish_status("error:missing_api_key")
            rospy.logerr("Set api_key in the chat configuration file")
            return

        messages = [{"role": "system", "content": self.system_prompt}]
        messages.extend(self.history)
        messages.append({"role": "user", "content": text})
        self._publish_status("requesting")

        try:
            reply = self._request_chat(self.api_key, messages)
        except (HTTPError, URLError, TimeoutError, OSError, ValueError, RuntimeError) as error:
            self._publish_status("error:request_failed")
            rospy.logerr("Bailian chat request failed: %s", error)
            return

        self.history.extend(
            [{"role": "user", "content": text}, {"role": "assistant", "content": reply}]
        )
        max_messages = self.max_history_turns * 2
        if max_messages == 0:
            self.history = []
        elif len(self.history) > max_messages:
            self.history = self.history[-max_messages:]

        self.reply_pub.publish(String(data=reply))
        print("大模型回复：{}".format(reply), flush=True)
        self._publish_status("reply_ready")

    def _request_chat(self, api_key, messages):
        request_body = json.dumps(
            {
                "model": self.model,
                "messages": messages,
                "max_tokens": self.max_tokens,
                "temperature": self.temperature,
                "stream": False,
            }
        ).encode("utf-8")
        request = Request(
            self.base_url + "/chat/completions",
            data=request_body,
            headers={
                "Authorization": "Bearer " + api_key,
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            with urlopen(request, timeout=self.timeout) as response:
                response_data = json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            details = error.read().decode("utf-8", errors="replace")
            raise RuntimeError("HTTP {}: {}".format(error.code, details[:500])) from error

        try:
            reply = response_data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as error:
            raise ValueError("Bailian response did not contain assistant text") from error
        if not isinstance(reply, str) or not reply.strip():
            raise ValueError("Bailian returned an empty assistant response")
        return reply.strip()


def main():
    rospy.init_node("chat_node")
    BailianChatNode()
    rospy.spin()


if __name__ == "__main__":
    main()