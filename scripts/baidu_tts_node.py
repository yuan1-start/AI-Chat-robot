#!/usr/bin/env python3

import json
import queue
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import rospy
import yaml
from std_msgs.msg import String


class BaiduTtsNode:
    def __init__(self):
        config_path = Path(rospy.get_param("~config_file")).expanduser()
        with config_path.open(encoding="utf-8") as stream:
            config = yaml.safe_load(stream) or {}

        self.api_key = str(config.get("api_key", "")).strip()
        self.secret_key = str(config.get("secret_key", "")).strip()
        self.token_url = config.get(
            "token_url", "https://aip.baidubce.com/oauth/2.0/token"
        )
        self.tts_url = config.get("tts_url", "https://tsn.baidu.com/text2audio")
        self.cuid = str(config.get("cuid", "spark_chat"))
        self.timeout = float(config.get("request_timeout_seconds", 20.0))
        self.max_text_bytes = int(config.get("max_text_bytes", 900))
        self.audio_options = {
            "lan": config.get("language", "zh"),
            "spd": int(config.get("speed", 5)),
            "pit": int(config.get("pitch", 5)),
            "vol": int(config.get("volume", 8)),
            "per": int(config.get("person", 0)),
            "aue": int(config.get("audio_format", 6)),
        }
        player_name = config.get("player", "paplay")
        self.player = shutil.which(player_name)
        self.access_token = ""
        self.token_expires_at = 0.0

        max_queue_size = max(1, int(config.get("max_queue_size", 5)))
        self.text_queue = queue.Queue(maxsize=max_queue_size)
        self.status_pub = rospy.Publisher(
            "/spark_chat/tts_status", String, queue_size=10
        )
        rospy.Subscriber(
            "/spark_chat/reply_text", String, self._on_reply, queue_size=10
        )

        worker = threading.Thread(target=self._worker, name="baidu-tts-worker")
        worker.daemon = True
        worker.start()
        if not self.api_key or not self.secret_key:
            rospy.logwarn("Set api_key and secret_key in config/tts.yaml to enable Baidu TTS")
        if not self.player:
            rospy.logerr("Audio player '%s' was not found", player_name)
        else:
            rospy.loginfo("Baidu online TTS ready; player=%s", self.player)

    def _publish_status(self, status):
        self.status_pub.publish(String(data=status))

    def _on_reply(self, message):
        text = message.data.strip()
        if not text:
            return
        try:
            self.text_queue.put_nowait(text)
        except queue.Full:
            rospy.logwarn("TTS queue is full; dropping a reply")
            self._publish_status("busy")

    def _worker(self):
        while not rospy.is_shutdown():
            try:
                text = self.text_queue.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                if not self.api_key or not self.secret_key:
                    raise RuntimeError("Baidu TTS credentials are missing in config/tts.yaml")
                if not self.player:
                    raise RuntimeError("Configured audio player is unavailable")
                self._publish_status("synthesizing")
                for chunk in self._split_text(text):
                    audio = self._synthesize(chunk)
                    self._publish_status("playing")
                    self._play(audio)
                self._publish_status("ready")
            except (HTTPError, URLError, TimeoutError, OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
                self._publish_status("error")
                rospy.logerr("Baidu TTS failed: %s", error)

    def _split_text(self, text):
        chunks = []
        current = ""
        punctuation = "。！？!?；;，,"
        for character in text:
            if len((current + character).encode("utf-8")) > self.max_text_bytes:
                split_at = max((current.rfind(mark) for mark in punctuation), default=-1)
                if split_at >= len(current) // 2:
                    chunks.append(current[: split_at + 1])
                    current = current[split_at + 1 :]
                else:
                    chunks.append(current)
                    current = ""
            current += character
        if current:
            chunks.append(current)
        return chunks

    def _get_access_token(self):
        if self.access_token and time.monotonic() < self.token_expires_at:
            return self.access_token

        query = urlencode(
            {
                "grant_type": "client_credentials",
                "client_id": self.api_key,
                "client_secret": self.secret_key,
            }
        )
        request = Request(self.token_url + "?" + query, method="GET")
        with urlopen(request, timeout=self.timeout) as response:
            result = json.loads(response.read().decode("utf-8"))

        token = result.get("access_token")
        if not token:
            error = result.get("error_description", result.get("error", "unknown error"))
            raise RuntimeError("Baidu OAuth token request failed: {}".format(error))

        self.access_token = token
        expires_in = int(result.get("expires_in", 0))
        self.token_expires_at = time.monotonic() + max(1, expires_in - 60)
        return self.access_token

    def _synthesize(self, text):
        data = {
            "tex": text,
            "tok": self._get_access_token(),
            "cuid": self.cuid,
            "ctp": 1,
        }
        data.update(self.audio_options)
        request = Request(
            self.tts_url,
            data=urlencode(data).encode("utf-8"),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                content = response.read()
                content_type = response.headers.get("Content-Type", "")
        except HTTPError as error:
            body = error.read(512).decode("utf-8", errors="replace")
            raise RuntimeError("Baidu TTS HTTP {}: {}".format(error.code, body)) from error

        if "json" in content_type.lower() or not content.startswith(b"RIFF"):
            try:
                result = json.loads(content.decode("utf-8"))
            except (UnicodeDecodeError, ValueError) as error:
                raise ValueError("Baidu TTS did not return WAV audio or a JSON error") from error
            raise RuntimeError(
                "Baidu TTS error {}: {}".format(
                    result.get("err_no", "unknown"),
                    result.get("err_msg", "unknown error"),
                )
            )
        return content

    def _play(self, audio):
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as wav_file:
            audio_path = wav_file.name
            wav_file.write(audio)
        try:
            subprocess.run([self.player, audio_path], check=True)
        finally:
            Path(audio_path).unlink(missing_ok=True)


def main():
    rospy.init_node("baidu_tts_node")
    BaiduTtsNode()
    rospy.spin()


if __name__ == "__main__":
    main()