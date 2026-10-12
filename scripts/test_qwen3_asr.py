#!/usr/bin/env python3
"""Run a local CPU smoke test for Qwen3-ASR.

Examples:
  python test_qwen3_asr.py --audio /tmp/asr_test.wav
    python test_qwen3_asr.py --record
"""

import argparse
from collections import deque
import shutil
import subprocess
import sys
import time
from pathlib import Path
import wave


DEFAULT_MODEL_PATH = (
    "/home/spark/ai_models/Qwen/Qwen--Qwen3-ASR-0.6B/snapshots/master"
)
DEFAULT_AUDIO_PATH = "/tmp/asr_test.wav"
DEFAULT_RECORD_OUTPUT = str(
    Path(__file__).resolve().parents[1] / "config" / "asr_test.wav"
)
SAMPLE_RATE = 16000
FRAME_DURATION_MS = 30
FRAME_BYTES = SAMPLE_RATE * FRAME_DURATION_MS // 1000 * 2
FRAME_DURATION_SECONDS = FRAME_DURATION_MS / 1000.0


def parse_args():
    parser = argparse.ArgumentParser(description="Test Qwen3-ASR on CPU")
    parser.add_argument("--model", default=DEFAULT_MODEL_PATH, help="Local model directory")
    parser.add_argument("--audio", default=DEFAULT_AUDIO_PATH, help="Input audio file")
    parser.add_argument(
        "--language",
        default="Chinese",
        help="Language hint, e.g. Chinese; use auto for automatic detection",
    )
    parser.add_argument("--threads", type=int, default=4, help="CPU inference threads")
    parser.add_argument(
        "--record",
        action="store_true",
        help="Record from the microphone and stop after VAD detects silence",
    )
    parser.add_argument(
        "--record-device",
        default="pulse",
        help="arecord microphone device name",
    )
    parser.add_argument(
        "--record-output",
        default=DEFAULT_RECORD_OUTPUT,
        help="Output WAV path when recording",
    )
    parser.add_argument(
        "--vad-aggressiveness",
        type=int,
        choices=range(4),
        default=2,
        help="WebRTC VAD aggressiveness from 0 (loose) to 3 (strict)",
    )
    parser.add_argument(
        "--silence-seconds",
        type=float,
        default=2.0,
        help="Continuous silence required to end an utterance",
    )
    parser.add_argument(
        "--start-timeout",
        type=float,
        default=15.0,
        help="Stop waiting if no speech is detected within this many seconds",
    )
    parser.add_argument(
        "--max-record-seconds",
        type=float,
        default=30.0,
        help="Safety cap; normal recording ends by VAD silence detection",
    )
    return parser.parse_args()


def read_pcm_frame(stream):
    frame = bytearray()
    while len(frame) < FRAME_BYTES:
        chunk = stream.read(FRAME_BYTES - len(frame))
        if not chunk:
            return None
        frame.extend(chunk)
    return bytes(frame)


def record_audio(
    output_path,
    device,
    vad,
    silence_seconds,
    start_timeout,
    max_record_seconds,
):
    if shutil.which("arecord") is None:
        raise RuntimeError("arecord was not found; install ALSA utilities or provide --audio")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        "arecord",
        "-q",
        "-D",
        device,
        "-f",
        "S16_LE",
        "-r",
        str(SAMPLE_RATE),
        "-c",
        "1",
        "-t",
        "raw",
    ]
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    pre_roll_frames = deque(maxlen=10)
    recorded_frames = []
    speech_started = False
    consecutive_voice_frames = 0
    silence_frames = 0
    start_time = time.monotonic()
    stop_reason = ""

    print("Listening; speak when ready. Recording stops after {:.2f}s of silence.".format(
        silence_seconds
    ))
    try:
        while True:
            frame = read_pcm_frame(process.stdout)
            if frame is None:
                break

            is_speech = vad.is_speech(frame, SAMPLE_RATE)
            if not speech_started:
                pre_roll_frames.append(frame)
                if is_speech:
                    consecutive_voice_frames += 1
                else:
                    consecutive_voice_frames = 0

                if consecutive_voice_frames >= 2:
                    recorded_frames.extend(pre_roll_frames)
                    pre_roll_frames.clear()
                    speech_started = True
                    print("Speech detected.")
                elif time.monotonic() - start_time >= start_timeout:
                    raise RuntimeError(
                        "No speech detected within {:.1f}s.".format(start_timeout)
                    )
                continue

            recorded_frames.append(frame)
            if is_speech:
                silence_frames = 0
            else:
                silence_frames += 1

            recorded_duration = len(recorded_frames) * FRAME_DURATION_SECONDS
            if silence_frames * FRAME_DURATION_SECONDS >= silence_seconds:
                stop_reason = "VAD detected {:.2f}s of silence".format(
                    silence_seconds
                )
                break
            if recorded_duration >= max_record_seconds:
                stop_reason = "safety cap of {:.1f}s reached".format(
                    max_record_seconds
                )
                break

        if not speech_started or not recorded_frames:
            return_code = process.poll()
            if return_code is None:
                try:
                    return_code = process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    return_code = None
            if return_code:
                error_output = process.stderr.read().decode("utf-8", errors="replace").strip()
                raise RuntimeError(
                    "Microphone capture failed (arecord exit code {}): {}".format(
                        return_code, error_output or "no details from arecord"
                    )
                )
            raise RuntimeError("No speech was captured from the microphone.")

        with wave.open(str(output_path), "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(SAMPLE_RATE)
            wav_file.writeframes(b"".join(recorded_frames))

        recorded_duration = len(recorded_frames) * FRAME_DURATION_SECONDS
        print("Recording saved: {} ({:.2f}s)".format(output_path, recorded_duration))
        print("Recording end: {}".format(stop_reason or "audio stream ended"))
    finally:
        if process.stdout:
            process.stdout.close()
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        if process.stderr:
            process.stderr.close()


def main():
    args = parse_args()
    model_path = Path(args.model).expanduser()
    audio_path = Path(args.record_output if args.record else args.audio).expanduser()

    if args.threads < 1:
        print("--threads must be at least 1", file=sys.stderr)
        return 2
    if args.silence_seconds <= 0 or args.start_timeout <= 0 or args.max_record_seconds <= 0:
        print("VAD silence, start timeout, and safety cap values must be positive.", file=sys.stderr)
        return 2
    if not (model_path / "model.safetensors").is_file():
        print("Model weights not found: {}".format(model_path / "model.safetensors"), file=sys.stderr)
        return 2

    try:
        import soundfile as sf
        import torch
        from qwen_asr import Qwen3ASRModel
    except ImportError as error:
        print("Qwen ASR dependencies are unavailable: {}".format(error), file=sys.stderr)
        print("Run this script with the spark-qwen-asr Conda environment.", file=sys.stderr)
        return 2

    try:
        if args.record:
            try:
                import webrtcvad
            except ImportError as error:
                raise RuntimeError(
                    "WebRTC VAD is unavailable; install webrtcvad-wheels in the ASR environment."
                ) from error
            vad = webrtcvad.Vad(args.vad_aggressiveness)
            record_audio(
                audio_path,
                args.record_device,
                vad,
                args.silence_seconds,
                args.start_timeout,
                args.max_record_seconds,
            )

        if not audio_path.is_file():
            print("Audio file not found: {}".format(audio_path), file=sys.stderr)
            return 2

        audio_info = sf.info(str(audio_path))
        if audio_info.frames == 0 or audio_info.samplerate <= 0:
            print("Audio file is empty or has an invalid sample rate.", file=sys.stderr)
            return 2

        duration = audio_info.frames / float(audio_info.samplerate)
        print("Audio: {}".format(audio_path))
        print(
            "Audio format: {} Hz, {} channel(s), {:.2f}s".format(
                audio_info.samplerate, audio_info.channels, duration
            )
        )
        print("PyTorch: {}, CUDA available: {}".format(torch.__version__, torch.cuda.is_available()))

        torch.set_num_threads(args.threads)
        load_start = time.perf_counter()
        model = Qwen3ASRModel.from_pretrained(
            str(model_path),
            dtype=torch.float32,
            device_map="cpu",
            max_inference_batch_size=1,
            max_new_tokens=512,
        )
        load_seconds = time.perf_counter() - load_start
        print("Model load time: {:.2f}s".format(load_seconds))

        language = None if args.language.lower() in ("auto", "none") else args.language
        infer_start = time.perf_counter()
        results = model.transcribe(audio=str(audio_path), language=language)
        infer_seconds = time.perf_counter() - infer_start

        if not isinstance(results, list):
            results = [results]
        for index, result in enumerate(results, 1):
            language_result = getattr(result, "language", "")
            text = getattr(result, "text", str(result))
            print("Result {} language: {}".format(index, language_result or "unknown"))
            print("Result {} text: {}".format(index, text))

        real_time_factor = infer_seconds / duration if duration > 0 else float("inf")
        print("Inference time: {:.2f}s".format(infer_seconds))
        print("RTF: {:.2f} (below 1.0 is faster than real time)".format(real_time_factor))
        return 0
    except subprocess.CalledProcessError as error:
        print("Microphone recording failed with exit code {}".format(error.returncode), file=sys.stderr)
        return error.returncode or 1
    except Exception as error:
        print("ASR test failed: {}: {}".format(type(error).__name__, error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())