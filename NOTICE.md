# Scope of the license

The toolkit's authored code, instructions and text examples are MIT licensed. The
video workflow is adapted from the author's `maker-video-agent` tools. No source
footage, participant photographs, voice recordings/clones, music recordings,
third-party logos, downloaded models or platform credentials are distributed.

Python, FFmpeg, Pillow, Playwright, faster-whisper, voice/video models and any
other optional engines keep their own licenses. Installing or invoking one does
not relicense it under MIT. No model weights or upstream model implementation
are bundled here. Brand/platform names identify destinations and technologies;
this toolkit is not an official product of those services.

## autocut（`skills/storytelling/video/autocut/`）

autocut 由作者的 `video-cut-skill` 并入，代码同为 MIT。它的第三方依赖都需要使用者自己安装
（`video/requirements-autocut*.txt`），各自保留自己的许可，安装或调用不会改变它们的许可。按 2026-10 核对的上游声明：

| 组件 | 用途 | 许可 | 备注 |
|---|---|---|---|
| FFmpeg | 解码/编码/滤镜 | 取决于构建（LGPL 或 GPL） | 不随仓库分发 |
| OpenCV（opencv-python-headless） | 逐帧特效、检测 | Apache-2.0 | 轮子内含的 FFmpeg 等组件有各自许可 |
| NumPy、PyYAML、Pydantic、Typer、Rich、httpx | 基础依赖 | BSD-3-Clause / MIT | |
| pyJianYingDraft | 写剪映草稿 | Apache-2.0 | 草稿格式由社区逆向，剪映升级可能失效；剪映软件及其素材库、VIP 内容不属于本项目，也不随仓库分发 |
| PySceneDetect | 可选镜头切分 | BSD-3-Clause | |
| faster-whisper | 可选转写（与 `video/scripts/transcribe.py` 共用） | MIT | 模型权重另有许可 |
| librosa / soundfile | 可选节拍检测 | ISC / BSD-3-Clause | |
| onnxruntime | 可选 YOLO 推理 | MIT | |
| YuNet（`face_detection_yunet_2023mar.onnx`，来自 OpenCV Zoo） | 可选人脸检测 | MIT | 由 `autocut models fetch yunet` 在使用者机器上下载，**不随仓库分发** |
| YOLO 检测权重 | 可选主体检测 | 取决于所选模型 | Ultralytics YOLOv8/11 权重为 AGPL-3.0（商用或闭源使用需另购授权）；仓库不含任何 YOLO 权重，请自行选择并核对许可 |

云端视觉/文本后端（阿里云百炼、Google Gemini）和本地 Ollama 模型只在使用者配置了密钥或服务时调用，
各自的服务条款与模型许可由使用者负责；会把缩小的关键帧发送到所选服务。自动音效为程序合成，
不含第三方音频；配乐必须是使用者有授权的音乐。设备预设（Insta360、Ray-Ban Meta 等）只是识别用的关键字，
品牌名仅用于指明设备，本工具包不是这些厂商的官方产品。

Creators retain responsibility for the material they choose to publish. The
fictional examples are for exercising the tools and are not real event reports
or measured technical claims.
