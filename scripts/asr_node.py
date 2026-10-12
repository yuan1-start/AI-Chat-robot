#!/usr/bin/env python3

import json
import subprocess
import threading
from pathlib import Path

import rospy
import yaml
from std_msgs.msg import String


class AsrNode:
    def __init__(self):
        config_path = Path(rospy.get_param("~config_file")).expanduser()
        with config_path.open(encoding="utf-8") as stream:
            config = yaml.safe_load(stream) or {}
        self.config = config.get("asr", {})
        self.python = self.config.get(
            "python_executable",
            "/home/spark/miniconda3/envs/spark-qwen-asr/bin/python",
        )
        self.worker_script = rospy.get_param("~worker_script")
        self.text_pub = rospy.Publisher(
            "/spark_chat/user_text", String, queue_size=10
        )
        self.status_pub = rospy.Publisher(
            "/spark_chat/asr_status", String, queue_size=10
        )
        self.shutdown_event = threading.Event()
        self.process_lock = threading.Lock()
        self.process = None
        rospy.on_shutdown(self._shutdown)
        self.worker_thread = threading.Thread(
            target=self._worker_loop, name="qwen-asr-worker"
        )
        self.worker_thread.daemon = True
        self.worker_thread.start()

    def _publish_status(self, status):
        self.status_pub.publish(String(data=status))

    def _worker_command(self):
        settings = self.config
        return [
            self.python,
            self.worker_script,
            "--model",
            settings["model_path"],
            "--language",
            str(settings.get("language", "Chinese")),
            "--threads",
            str(settings.get("threads", 4)),
            "--record-device",
            str(settings.get("record_device", "pulse")),
            "--record-output",
            str(settings.get("record_output", "/tmp/spark_chat_asr.wav")),
            "--vad-aggressiveness",
            str(settings.get("vad_aggressiveness", 1)),
            "--silence-seconds",
            str(settings.get("silence_seconds", 2.0)),
            "--start-timeout",
            str(settings.get("start_timeout", 300.0)),
            "--max-record-seconds",
            str(settings.get("max_record_seconds", 30.0)),
        ]

    def _handle_worker_line(self, line):
        try:
            event = json.loads(line)
        except ValueError:
            rospy.logwarn("Ignoring invalid ASR worker output")
            return

        event_type = event.get("event")
        if event_type == "ready":
            self._publish_status("listening")
            rospy.loginfo("Qwen ASR is ready and listening")
        elif event_type == "recognized":
            text = event.get("text", "").strip()
            if text:
                rospy.loginfo("ASR recognized: %s", text)
                self.text_pub.publish(String(data=text))
                self._publish_status("recognized")

    def _worker_loop(self):
        while not self.shutdown_event.is_set() and not rospy.is_shutdown():
            self._publish_status("starting")
            try:
                process = subprocess.Popen(
                    self._worker_command(),
                    stdout=subprocess.PIPE,
                    stderr=None,
                    universal_newlines=True,
                    encoding="utf-8",
                    errors="replace",
                    bufsize=1,
                )
            except OSError as error:
                rospy.logerr("Cannot start Qwen ASR worker: %s", error)
                self._publish_status("error:worker_start_failed")
                self.shutdown_event.wait(5.0)
                continue

            with self.process_lock:
                self.process = process
            try:
                for line in process.stdout:
                    if self.shutdown_event.is_set() or rospy.is_shutdown():
                        break
                    if line.strip():
                        self._handle_worker_line(line)
            finally:
                if process.stdout:
                    process.stdout.close()
                return_code = process.wait()
                with self.process_lock:
                    if self.process is process:
                        self.process = None

            if not self.shutdown_event.is_set() and not rospy.is_shutdown():
                rospy.logwarn(
                    "Qwen ASR worker exited with code %s; restarting", return_code
                )
                self._publish_status("restarting")
                self.shutdown_event.wait(3.0)

    def _shutdown(self):
        self.shutdown_event.set()
        with self.process_lock:
            process = self.process
        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


def main():
    rospy.init_node("asr_node")
    AsrNode()
    rospy.spin()


if __name__ == "__main__":
    main()