# Qwen3-ASR 本地测试说明

本文说明 `test_qwen3_asr.py` 的用途、运行环境和启动方式。脚本用于在机器人上单独验证 Qwen3-ASR-0.6B，不启动 ROS 节点，也不会控制底盘。

## 脚本作用

脚本会在 CPU 上执行以下流程：

1. 检查本地模型权重和输入音频是否存在。
2. 可选地调用 `arecord` 从麦克风录音。
3. 以 FP32 加载 Qwen3-ASR-0.6B。
4. 转写音频并输出识别语言、识别文本、模型加载耗时、推理耗时和实时率 RTF。

脚本默认使用的模型目录：

```text
/home/spark/ai_models/Qwen/Qwen--Qwen3-ASR-0.6B/snapshots/master
```

## 前置条件

- 已创建 Conda 环境 `spark-qwen-asr`。
- 该环境已安装 CPU 版 PyTorch、`qwen-asr`、`soundfile` 等依赖。
- 麦克风录音使用 WebRTC VAD；如尚未安装，可在该环境中运行 `python -m pip install webrtcvad-wheels`。
- 模型目录中有 `model.safetensors`、配置文件和 tokenizer 文件。
- 麦克风录音模式需要系统安装 `arecord`，并且 ALSA/PulseAudio 能访问麦克风。默认通过 `pulse` 设备采集，避免与桌面 PulseAudio 服务争抢物理声卡。

## 测试已有音频

确认音频文件可访问后运行：

```bash
/home/spark/miniconda3/envs/spark-qwen-asr/bin/python \
  /home/spark/spark_noetic/src/spark_app/spark_chat/scripts/test_qwen3_asr.py \
  --audio /tmp/asr_test.wav
```

音频默认按中文识别提示处理。使用语言自动检测：

```bash
/home/spark/miniconda3/envs/spark-qwen-asr/bin/python \
  /home/spark/spark_noetic/src/spark_app/spark_chat/scripts/test_qwen3_asr.py \
  --audio /tmp/asr_test.wav \
  --language auto
```

## 录音并测试

运行后请对着麦克风说话，停下后等待约 2 秒，VAD 会自动判定本句结束并开始转写。录音保存为 `spark_chat/config/asr_test.wav`：

```bash
/home/spark/miniconda3/envs/spark-qwen-asr/bin/python \
  /home/spark/spark_noetic/src/spark_app/spark_chat/scripts/test_qwen3_asr.py \
  --record
```

录音格式为 16 kHz、单声道、16-bit PCM。正常结束条件是 VAD 检测到连续静音；默认需等待语音开始的时间为 15 秒，最大录音 30 秒仅为异常保护上限，不是正常的停止条件。VAD 激进度默认为 2，范围 0 到 3，值越大越容易把较轻的声音判为静音。如果检测不到较轻的语音，可先尝试降低激进度：

```bash
/home/spark/miniconda3/envs/spark-qwen-asr/bin/python \
  /home/spark/spark_noetic/src/spark_app/spark_chat/scripts/test_qwen3_asr.py \
  --record \
  --vad-aggressiveness 1 \
  --silence-seconds 1.0
```

如果 PulseAudio 默认输入不是目标麦克风，可在系统声音设置中选择输入设备，或用 `pactl list short sources` 查看输入源并设置默认源。也可以通过 `--record-device` 覆盖 ALSA 设备，例如 `--record-device plughw:CARD=Device,DEV=0`；但若桌面 PulseAudio 正在占用该物理声卡，直接使用 `plughw` 可能报设备忙，应优先使用 `pulse`。

## 参数

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `--model` | 配置中的本地模型目录 | 指定模型 snapshot 目录 |
| `--audio` | `/tmp/asr_test.wav` | 指定已有音频文件；录音模式会忽略此项 |
| `--language` | `Chinese` | 识别语言提示；设为 `auto` 自动检测 |
| `--threads` | `4` | PyTorch CPU 推理线程数 |
| `--record` | 关闭 | 启用麦克风录音，并在 VAD 判断语句结束后自动停止 |
| `--record-device` | `pulse` | `arecord` 使用的 ALSA 输入设备；通过 PulseAudio 默认输入采集 |
| `--record-output` | `spark_chat/config/asr_test.wav` | 麦克风录音输出文件，默认路径基于脚本位置计算 |
| `--vad-aggressiveness` | `2` | WebRTC VAD 激进度，`0` 最宽松，`3` 最严格 |
| `--silence-seconds` | `2.0` | 连续静音达到该时长后判定一句话结束 |
| `--start-timeout` | `15.0` | 等待首次检测到语音的最长时间 |
| `--max-record-seconds` | `30.0` | 异常保护上限；正常情况由静音 VAD 结束 |

完整参数列表可运行：

```bash
/home/spark/miniconda3/envs/spark-qwen-asr/bin/python \
  /home/spark/spark_noetic/src/spark_app/spark_chat/scripts/test_qwen3_asr.py \
  --help
```

## 输出说明

- `Model load time`：模型加载耗时。
- `Inference time`：本次音频推理耗时。
- `RTF`：推理耗时除以音频时长；小于 `1.0` 表示本次推理快于实时。
- `Result ... text`：模型识别出的文字。准确率应使用清晰、内容已知的完整语句评估，短暂静音或噪声样本不能代表识别效果。

## 常见问题

- `Model weights not found`：确认 `--model` 指向包含 `model.safetensors` 的 snapshot 目录。
- `Audio file not found`：确认 `--audio` 路径正确，或改用 `--record` 录音。
- `arecord was not found`：安装 ALSA 工具，或使用已有音频文件测试。
- `No speech detected`：检查麦克风是否有输入以及系统默认输入源；较轻的语音可将 `--vad-aggressiveness` 调低。
- `Microphone capture failed ... Device or resource busy`：物理声卡正被 PulseAudio 等服务占用；使用默认的 `--record-device pulse`，不要直接访问忙碌的 `plughw` 设备。
- 麦克风设备打开失败：运行 `arecord -l` 查看设备，再通过 `--record-device` 指定设备。
- tokenizer 文件解码报错：检查模型目录中的 `merges.txt` 是否为 UTF-8 文本，并确保整份模型文件已完整传输。