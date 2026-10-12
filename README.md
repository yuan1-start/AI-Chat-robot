# spark_chat

用于机器人语音 AI 对话的 ROS 包。ASR、聊天模型和 TTS 的 ROS 接入代码统一放在本包中，与现有语音导航节点分开。

## 数据流

```text
麦克风 -> ASR -> /spark_chat/user_text
                   -> 聊天模型 -> /spark_chat/reply_text -> TTS -> 扬声器
```

ASR 使用独立 Conda 子进程常驻加载模型，并通过 ROS 话题将识别结果交给聊天节点。聊天话题不复用 `/voice/stt`，避免识别文本被现有语音导航节点当作底盘指令。

## 目录

- `scripts/`：ASR、聊天和 TTS 节点
- `launch/`：组合启动文件
- `config/`：模型和服务配置

模型权重建议放在包目录之外，并通过 ROS 参数或配置文件指定路径，避免大型模型文件进入源码管理。

## ASR 选型

首版使用 ModelScope 上的 `Qwen/Qwen3-ASR-0.6B`。默认按当前机器人可用的 CPU 使用 FP32 推理，模型目录配置为 `/home/spark/ai_models/Qwen/Qwen--Qwen3-ASR-0.6B/snapshots/master`，具体参数见 `config/asr.yaml`。模型下载后保留 ModelScope 的仓库目录结构并传到该路径，或修改配置中的 `model_path`。

Qwen3-ASR 的 Python 推理环境与 ROS Noetic 系统 Python 可能不兼容；实现时应将模型推理与 ROS 节点隔离，并通过本机接口转发音频/识别文本。CPU 推理速度需在目标设备上实测。

## 一键启动 ASR 与聊天

确认 `config/chat.yaml` 中已设置百炼 API Key 后，在一个终端运行：

```bash
source /home/spark/spark_noetic/devel/setup.bash
roslaunch spark_chat chat.launch
```

`roslaunch` 会在需要时自动启动 ROS Master，同时启动麦克风 ASR、云端聊天和百度在线 TTS 节点。ASR 识别到一句话后发布到 `/spark_chat/user_text`，聊天回复发布到 `/spark_chat/reply_text`，并以原始中文打印在此启动终端；TTS 节点将回复合成为 WAV 并通过 PulseAudio 播放。ASR 模型在 Conda 子进程中只加载一次；启动后请等待模型加载完成，再对麦克风说话。`config/asr.yaml` 中的 `python_executable` 需要指向安装了 Qwen ASR 依赖的 Conda Python。

调试时可另开终端查看 `/spark_chat/asr_status`、`/spark_chat/status` 和 `/spark_chat/reply_text`；正常使用不需要手工运行 `rostopic pub` 或单独启动 `roscore`。

## 聊天模型

聊天节点通过阿里云百炼的 OpenAI 兼容 Chat Completions 接口调用千问模型，默认模型为 `qwen3.8-flash`。配置见 `config/chat.yaml`，启动方式为：

```bash
nano /home/spark/spark_noetic/src/spark_app/spark_chat/config/chat.yaml
chmod 600 /home/spark/spark_noetic/src/spark_app/spark_chat/config/chat.yaml
source /home/spark/spark_noetic/devel/setup.bash
roslaunch spark_chat chat.launch
```

将百炼 API Key 填到 `config/chat.yaml` 的 `api_key: ""` 双引号中。配置文件由节点在本机读取，Key 不会加载到 ROS 参数服务器。请勿提交含真实 Key 的配置文件；`chmod 600` 用于限制本机其他用户读取。API Key 必须与百炼 API endpoint 属于同一地域；可在 `chat.yaml` 中配置业务空间专属 endpoint。聊天请求会将 ASR 转写文本和有限轮数的对话上下文发送到云端。节点订阅 `/spark_chat/user_text`，发布完整回复到 `/spark_chat/reply_text`，状态发布到 `/spark_chat/status`。可向 `/spark_chat/reset` 发布 `std_msgs/Empty` 清空对话上下文。

百度在线 TTS 凭据和发音参数配置在 `config/tts.yaml`。填写新创建或轮换后的 `api_key` 与 `secret_key`，并执行 `chmod 600 /home/spark/spark_noetic/src/spark_app/spark_chat/config/tts.yaml` 限制文件权限；不要复用已出现在旧源码中的凭据。TTS 节点订阅 `/spark_chat/reply_text`，状态发布到 `/spark_chat/tts_status`。接口使用 HTTPS，音频通过 `paplay`（PulseAudio）播放。

节点按完整回复发布，第一版不启用流式输出；网络错误或超时会发布状态并记录日志，不会把错误文本发给 TTS。聊天模型输出仅作为对话回复，不应直接用于底盘或机械臂控制。

## 依赖

当前包的 ROS 基础依赖为 `rospy` 和 `std_msgs`。ASR、聊天后端和 TTS 的 Python 依赖将在各节点确定后单独添加，避免把不同推理环境强行装进 ROS Noetic 的系统 Python。