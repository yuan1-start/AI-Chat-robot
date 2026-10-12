# AI-Chat-robot
记录spark机器人中的AI聊天机器人助手

## spark_chat

ROS package for a voice-driven AI conversation pipeline. It includes ASR, cloud chat, and online TTS integration for ROS Noetic-based robots.

## Overview

This package connects three stages:

```text
Microphone -> ASR -> /spark_chat/user_text -> chat model -> /spark_chat/reply_text -> TTS -> speaker
```

The design keeps the model inference and ROS runtime separate, which is important for Qwen ASR and ROS Noetic compatibility.

## Features

- Qwen ASR integration via a dedicated Python subprocess
- Aliyun Bailian / DashScope-compatible chat model API
- Baidu online TTS synthesis via short-text API
- ROS topic-based data flow
- Minimal status topics for debugging

## Package Structure

- `scripts/` : Python nodes
- `launch/` : launch files
- `config/` : YAML configuration

## Quick Start

1. Copy the example config files or create local files for your own keys.
2. Fill in your real API keys in the local config files.
3. Build the catkin workspace:

```bash
cd /home/spark/spark_noetic
catkin_make
source devel/setup.bash
```

4. Start the full speech pipeline:

```bash
roslaunch spark_chat chat.launch
```

## Configuration

### ASR

Edit `config/asr.yaml` and point `python_executable` to the Conda environment that contains the Qwen ASR dependencies.

### Chat

Edit `config/chat.yaml` and set your DashScope / Bailian API key.

### TTS

Edit `config/tts.yaml` and set your Baidu API key and secret. Then set `person` to the voice you want to use.

## Important Safety Notice

Do not commit real secrets to Git. Use placeholder values in public repositories and keep real local files outside of version control.

## ROS Topics

- `/spark_chat/user_text` : ASR text input
- `/spark_chat/reply_text` : model reply text
- `/spark_chat/status` : chat node status
- `/spark_chat/tts_status` : TTS status

## Notes

- The project is designed for short spoken replies and voice-friendly prompts.
- TTS uses temporary WAV output and plays it with `paplay`.
- Large model files should not be stored in the repository.

### License

MIT
