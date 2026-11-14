# 场景工程与本机后端

场景包保存“CG 在哪里、与谁互动”的证据，效果脚本负责创意。Agent 可通过 Blender CLI 构建和渲染；已有社区 MCP 连接时，也可交互查看、修改同一个 Blender 工程。连接状态单独检查，不能从 .blend 文件推断已配置 MCP。

## 处理路径

- `camera.mode: reconstructed`：本地 DA3 Small 多视图推理，加真实 SIFT 三维/二维对应和 PnP 检查，相机为相对尺度。参考视图网格可以用于遮挡、阴影和效果附着，单张图片只构成单视图先验。
- `segmentation.objects`：SAM 2.1 Tiny 视频蒙版。每项包含唯一 id、role，以及第一帧归一化 points/labels 或 box。role 为 target 或 foreground。box 为 [x0,y0,x1,y1]。Agent 根据画面指定，不能从文件名猜对象。
- `clean_plate`：object_id 加实际 reference 图片，或省略 reference 调用本地 LaMa。参考经光流传播，并保护原片前景。透视、边界、运动跨度和补全内容需逐镜头检查。
- `render.engine: cycles`：本地 Cycles、实际 GPU 名称 gpu、采样数 samples。环境的 shadow_catcher 需要该引擎。
- `scene_analysis.lighting.area_lights`：每项包含 name/location/energy/color/size，记录推断光源。有实际 HDRI 时放入 assets，再通过 lighting.hdri_asset 指定资源名和 environment_strength。

当前视频分割从第零帧初始化；中途第一次出现的对象另选镜头或增加专门处理。查看 segmentation.json 的 review_frames，不能掩盖丢失目标或剧烈面积突变。

本机私有 scene_runtime 配置包含 gpu_python、pythonpaths、device、da3_model、sam2_checkpoint、lama_model。工作台从 `.runtime/cg.runtime.json` 读取；全局 skill 从 runtime.local.json.scene_runtime 读取。推理离线运行，模型先下载并记录来源。新增依赖放在独立 CG 目录，不修改语音环境的软件包。

## 工程产物

| 文件 | 用途与范围 |
|---|---|
| camera.json、track-3d-*.jpg | 位姿、内参和所测对应点的逐帧误差；未承诺真实标定尺寸 |
| multiview-prediction.npz | 输入视图的深度、置信度和相机预测，供进一步融合 |
| perception.npz、perception.json | 参考视图的世界坐标、来源、相对尺度与核对 |
| masks/、segmentation.json | 视频蒙版、前景联合蒙版和需要回看的帧 |
| clean-reference.png、clean-plate.json | 使用的真实参考或生成补景及依据 |
| tracked-effect.blend | 可编辑的相机、环境、灯光、对象与动画 |
| CG-preview-*.png | 与最终视频共用合成路径的静帧 |
| CG-effect.mp4、CG-before-after.mp4 | 实际成片及前后对比 |

先用中性网格核对实物轮廓与投影，再制作效果。硬质表面可从点云拟合；曲面保留深度形状，需要背面时补实际模型或有依据的代理。碰撞代理只是模拟输入，实际碰撞还需本片运行模拟并验收。

查看起效、最大运动、遮挡交叉和结束复位。漂亮的静帧不能证明整段稳定；不同题材和运动类型分别留验证样本。未测的类型保持未验证。音频仍按本片的默认配乐和主观试听要求执行。

## 合成调整

原片已经拍下实物的阴影时，直接再叠 CG 阴影可能过重。对不透明物体，可用 `cg recompose 原渲染目录 --out 新版本 --shadow-strength 0到1` 生成独立覆盖蒙版，再单独调节阴影。该步骤复用已有三维结果和音轨，不修改原工程或重跑模型，记录 parent_job 与后期参数。透明玻璃、体积、复杂折射需要专用渲染通道；该覆盖蒙版路径未覆盖这些材质。它也不等于已移除原片中的旧阴影或完成完整的差分光照。
