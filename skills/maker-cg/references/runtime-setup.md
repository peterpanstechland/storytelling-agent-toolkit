# 独立运行环境

本 Skill 用 Blender CLI 构建原生工程，不要求 MCP 连接。MCP 可作为已有环境的交互入口，连接是否可用需另行检查。Agent 负责看素材、编写本片计划和场景脚本，模型推理不会自动理解所有产品或生成所有特效。

## 基础路径

在独立 Python 环境安装本 Skill 的 `requirements.txt`，并单独安装 Blender、FFmpeg 与 FFprobe。以下命令在仓库根目录运行；安装到其他位置后使用实际 Skill 路径。

```bash
python -m pip install -r skills/maker-cg/requirements.txt
python skills/maker-cg/scripts/cg.py doctor
python skills/maker-cg/scripts/cg.py inspect /path/to/shot.mp4 --out /path/to/work/inspect-v1
```

将 `runtime.example.json` 复制为同目录的 `runtime.local.json`，填写本机路径，或将 Blender、FFmpeg、FFprobe 放入 PATH。FFprobe 需与 FFmpeg 位于同一目录。`python` 供 Agent 选择主脚本环境，不会由脚本自动创建环境。Windows 路径在 JSON 中可用正斜杠。该示例只有占位路径，复制后仍需实际安装与检查。

基础平面、固定机位和外部相机模式不需要深度或分割权重。`doctor` 报告工具及文件的可见状态，不代表 GPU 推理或整段视觉验收成功。计划字段、短样和渲染命令见 [计划与运行约定](plan-and-run.md)。

## 可选场景模型

`reconstructed`、视频分割与自动补景使用单独的 `scene_runtime.gpu_python`。在独立环境按各项目的官方说明安装其代码及匹配的 PyTorch/CUDA 依赖，不能仅复制配置就声称模型可用，也不要将 CG 包安装进现有声音环境。

| 用途 | 代码与模型 | 本地配置 |
|---|---|---|
| 多视图深度与相机先验 | [Depth Anything 3](https://github.com/ByteDance-Seed/Depth-Anything-3)、[DA3 Small](https://huggingface.co/depth-anything/DA3-SMALL) | `da3_model` 指向完整的本地模型目录；`pythonpaths` 包含其 `src` 或已安装的包目录 |
| 对象与前景视频蒙版 | [SAM 2.1](https://github.com/facebookresearch/sam2)，Tiny 权重 | `sam2_checkpoint` 指向 `sam2.1_hiera_tiny.pt`；该代码目前按 CUDA bfloat16 路径执行，未验证 CPU 退路 |
| 参考帧补景 | [LaMa](https://github.com/advimman/lama)，[IOPaint 分发的 TorchScript 权重](https://github.com/Sanster/IOPaint) | `lama_model` 指向 `big-lama.pt`，无需安装 IOPaint 服务 |

示例 `pythonpaths` 只展示源码入口；如果第三方依赖另装在专用目录，也需将该目录加入此列表。worker 使用这里的列表替换继承的 PYTHONPATH，以隔离推理依赖。模型提前下载，保留版本、来源、许可及 SHA256，推理阶段离线运行。当前代码不会自动下载模型或创建这一环境。

基础 `reconstruction.depth_model` 还可选择独立的 Depth Anything V2 Small HF 路径，需要其完整本地模型目录、torch 和 transformers；该路径是单视图相对深度，不能替代多视图相机解算。

单独验证模型载入与短镜头推理，再检查实际跟踪、遮罩、补景和 Blender 合成。当前可见网格来自参考视图，没有隐藏面的真实重建或物理尺度保证。树木生长、手部配饰和大幅绕拍各需对应实现与素材验收。

## 本地文件

原片、本人录音、音乐、权重、`runtime.local.json`、生成的 `scene-runtime.private.json`、`.blend` 与成片保留在使用者工作目录。安装器只复制公开 Skill 源码，不迁移私人运行配置。音乐使用实际授权文件；最终音轨需要试听，机器检查不能代替听辨。
