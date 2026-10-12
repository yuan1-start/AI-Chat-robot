#!/usr/bin/env python3

import argparse
from contextlib import redirect_stdout
import json
import signal
import sys
import time
from pathlib import Path

from test_qwen3_asr import record_audio


def parse_args():
    parser = argparse.ArgumentParser(description="Persistent Qwen3-ASR microphone worker")
    parser.add_argument("--model", required=True)
    parser.add_argument("--language", default="Chinese")
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--record-device", default="pulse")
    parser.add_argument("--record-output", required=True)
    parser.add_argument("--vad-aggressiveness", type=int, choices=range(4), default=1)
    parser.add_argument("--silence-seconds", type=float, default=2.0)
    parser.add_argument("--start-timeout", type=float, default=300.0)
    parser.add_argument("--max-record-seconds", type=float, default=30.0)
    return parser.parse_args()


def emit(event, **fields):
    payload = {"event": event}
    payload.update(fields)
    print(json.dumps(payload, ensure_ascii=False), flush=True)


def stop_worker(_signum, _frame):
    raise KeyboardInterrupt


def main():
    args = parse_args()
    model_path = Path(args.model).expanduser()
    output_path = Path(args.record_output).expanduser()
    if not (model_path / "model.safetensors").is_file():
        print("Model weights not found: {}".format(model_path / "model.safetensors"), file=sys.stderr)
        return 2
    if args.threads < 1 or min(
        args.silence_seconds, args.start_timeout, args.max_record_seconds
    ) <= 0:
        print("ASR thread and timing settings must be positive.", file=sys.stderr)
        return 2

    try:
        import torch
        import webrtcvad
        from qwen_asr import Qwen3ASRModel
    except ImportError as error:
        print("Qwen ASR dependencies are unavailable: {}".format(error), file=sys.stderr)
        return 2

    signal.signal(signal.SIGTERM, stop_worker)
    signal.signal(signal.SIGINT, stop_worker)
    try:
        with redirect_stdout(sys.stderr):
            torch.set_num_threads(args.threads)
            model = Qwen3ASRModel.from_pretrained(
                str(model_path),
                dtype=torch.float32,
                device_map="cpu",
                max_inference_batch_size=1,
                max_new_tokens=512,
            )
        vad = webrtcvad.Vad(args.vad_aggressiveness)
        emit("ready")

        while True:
            try:
                with redirect_stdout(sys.stderr):
                    record_audio(
                        output_path,
                        args.record_device,
                        vad,
                        args.silence_seconds,
                        args.start_timeout,
                        args.max_record_seconds,
                    )
                    results = model.transcribe(
                        audio=str(output_path),
                        language=(
                            None
                            if args.language.lower() in ("auto", "none")
                            else args.language
                        ),
                    )
                if not isinstance(results, list):
                    results = [results]
                for result in results:
                    text = getattr(result, "text", str(result)).strip()
                    language = getattr(result, "language", "")
                    if text:
                        emit("recognized", text=text, language=language)
                        break
            except RuntimeError as error:
                if str(error).startswith("No speech detected within"):
                    print(str(error), file=sys.stderr)
                    continue
                raise
    except KeyboardInterrupt:
        return 0
    except Exception as error:
        print("ASR worker failed: {}: {}".format(type(error).__name__, error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())