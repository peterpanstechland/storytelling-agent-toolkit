# 计划与本地运行

普通脚本依赖 Python 3、numpy、OpenCV 和 Pillow，Blender worker 使用已安装 Blender 的原生 Python，编码通过 FFmpeg 与 FFprobe。脚本不会下载模型、上传素材或调用付费服务。

在剪辑大师工作台先用 python studio.py cg doctor 检查。独立使用时，脚本为本 skill 的 scripts/cg.py，可用顶层 --ffmpeg 和 --blender 指定本机二进制路径。默认也能从 PATH、标准 Windows Blender 安装目录和工作台 .runtime 中发现工具。

全局安装可有本机私有的 runtime.local.json，字段 python、ffmpeg、blender、studio_root 为实际路径。工具优先读取其中二进制位置，跨项目调用时使用配置的 Python 环境。可选 depth_model 是本机已有深度权重的路径，Agent 在本片适用时将其填入 reconstruction.depth_model。该文件随本机安装生成。

## Agent 编写计划

创建一个合法 JSON 文件，路径相对计划文件解析。下面只说明 schema，实际执行时填入已观察的素材和四角。

| 字段 | 意义 |
|---|---|
| source | 已归一的单镜头视频或 PNG/JPEG 等图片，保持原片独立保存 |
| start / duration | 源内秒数，初次选 5–10 秒，工具上限 30 秒 |
| fps / width | 渲染帧率与宽度，初次用 24 fps、1280 宽，宽度须为偶数 |
| color.status / color.evidence | normalized_sdr 与本次技术归一的依据或记录 |
| plane.corners | 第一帧的左上、右上、右下、左下四角，分别为归一化的 x、y |
| plane.aspect | 实际平面宽度除以高度，无法测量时标明近似 |
| plane.focal_width_ratio | 焦距像素值除以画面宽度，默认 1.05 为估算 |
| effect.preset / effect.seed | voxel-bloom、voxel-scatter 或 portal，以及可复现的随机种子 |
| camera.mode | planar、fixed、imported、reconstructed，默认 planar；后者需本机场景模型 |
| camera.reference_region | fixed 模式中用于核对机位的静止背景矩形，避免把移动物体当背景 |
| camera.file | imported 模式的相机 JSON，采用 Blender matrix_world 约定 |
| scene_script | 本片自定义 build_scene(context) 场景脚本，设置后由该脚本构建效果 |
| assets | 资源名与本机模型/贴图路径的映射 |
| scene_analysis | 实际关键帧、结构、材质、光向、效果设计及几何依据；参见 scene-aware.md |
| reconstruction.depth_model / relief_strength | 本地可选 Depth Anything V2 Small 路径和相对深度起伏强度；原片始终留在本机 |
| effect.placement | 锚点、尺寸、离面距离、旋转与模型原点，见自定义接口 |
| effect.blend_envelope | 可选的递增 [秒, 合成不透明度] 对；不透明度为 0–1，配合动作前后静止段平滑融入原片 |
| foreground_mask | 白色区域保护实拍前景的静态图或与本片起点对齐的遮罩视频 |
| segmentation.objects | Agent 按实拍指定目标/前景的初始点与框，SAM 2.1 生成视频蒙版 |
| clean_plate | object_id 与可选实际 reference；省略 reference 时调用本地 LaMa |
| reconstruction.views / process_res | 多视图预测的关键帧数量与处理分辨率；图片按单视图处理 |
| render.engine / gpu / samples | eevee 或 cycles、实际 GPU 名称和采样数；阴影接收需要 cycles |
| music / music_offset / music_provenance | 获授权的 BGM 文件、截取秒数和来源 |

音轨默认在底片有声音时保留原声并压低 BGM。明确需要音乐短样时设置 audio.original 为 mute。复杂的多轨对白混音继续接本片已有后期工程，成片需试听。

## 分阶段验证

先运行 prepare，查看输出的 track-*.jpg 和 camera.json。该阶段提取真实底片，计算各帧对应点、平面与近似镜头。不可靠帧会报错，修正选面、素材起点或镜头范围后使用新版本。

命令入口为以下三种，PLAN 和 OUTPUT 使用本机真实路径。

```text
python studio.py cg prepare PLAN --out OUTPUT
python studio.py cg render PLAN --out OUTPUT --still 84
python studio.py cg render PLAN --out OUTPUT
```

--still 选择的是从零开始的动画帧，用于先看材质与空间关系。完整 render 复用相同计划的跟踪及已生成帧，完成其余渲染与混音。若渲染已完成但合成中断，用 finish PLAN --out OUTPUT 接续。

输出目录绑定计划、源文件状态与脚本哈希。修改内容用新目录，避免把旧渲染帧混入新片。运行锁记录本次进程，异常中断后先确认对应 PID 已退出再清理孤立锁。

## 看得见的验收

camera.json 的 median_match_error_px 是参与平面跟踪的图像点中位误差，corner_reprojection_rms_px 是近似相机投影四角与跟踪四角的误差。两者衡量不同环节，不能当作全场景建模精度。实际素材中的遮挡和漂移仍需抽查动态画面。

tracked-effect.blend 保存三维几何、光照和烘焙的镜头动画。渲染出的透明图层与实拍在线性光下合成，再编码为 SDR 视频。用户可以继续用 Blender 调整效果。

本工具复用的主要算法与接口见 [OpenCV 单应变换](https://docs.opencv.org/4.x/d9/dab/tutorial_homography.html)、[OpenCV solvePnP](https://docs.opencv.org/4.x/d5/d1f/calib3d_solvePnP.html) 和 [Blender Python API](https://docs.blender.org/api/current/)。第三方运行时许可证随原安装保留，本项目代码独立实现其调用与效果设计。
