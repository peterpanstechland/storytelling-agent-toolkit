# 自定义场景接口

为每个新想法生成独立的本片 Python 场景文件，通过计划中的 scene_script 引用。通用引擎继续处理底片、镜头动画、渲染与合成。用户用自然语言描述需求，Agent 完成脚本。

脚本定义 build_scene(context)。context 中有 bpy、scene、camera、job、plan、fps 和 duration，可直接使用 Blender 的原生网格、曲线、Geometry Nodes、粒子替代几何、关键帧与模拟能力。

引擎同时提供下列可复用接口。

| 名称 | 用途 |
|---|---|
| material(name, color, metallic, roughness, emission) | 创建原生 Principled 材质，color 为 0–1 的显示 RGB |
| cube(name, at, dimensions, mat, bevel) | 生成带倒角的立方体 |
| tube(name, points, radius, mat) | 使用贝塞尔曲线生成管线和轨迹 |
| pose(obj, seconds, location, rotation, scale) | 写入本片时间下的位置、欧拉旋转和缩放关键帧 |
| import_model(name) | 导入 plan.assets 中对应的 GLB/GLTF、OBJ 或 FBX，返回导入的对象，保留模型层级 |
| source_surface(name, polygon, thickness, depth, texture, side_material, grid, relight) | 从已观察的源图区域建立网格、源图 UV 与厚度；polygon 为所跟踪平面中的归一化多边形 |
| visible_mesh(name, mask, step, material, thickness, geometry) | 根据参考视图的世界坐标和对象蒙版建网格；geometry 为 depth 或点云拟合的 plane |
| environment_mesh(exclude_object, step, shadow_catcher) | 建立环境网格，避开被编辑的物体，作为遮挡、阴影与碰撞代理 |
| photograph_material() | 使用源图纹理、参考法线和近似重照明的共享材质 |
| fracture(object_id, pieces, spread, lift, thickness, start, opened, hold, closed, geometry) | 按实际对象轮廓与点云生成碎片，由本片脚本编排运动 |

素材路径经计划文件解析为绝对路径，资源内容参与任务签名。场景也可以读取 plan 中自己定义的效果参数，用于控制颜色、数量、轨迹、触发、风格和物理模拟。不要让用户为普通制作请求手填 Blender 参数。

`source_surface` 默认使用第一帧原片投影纹理。启用 reconstruction.depth_model 时，几何取自可见相对深度，否则落在跟踪平面。`texture` 可提供另一张实际参考，按整个跟踪面的 UV 采样；`depth` 是世界 Z 偏移，`side_material` 控制厚度侧面。网格精度由 grid 决定，细边界先提高精度并核对轮廓。

照片材质默认保留原片曝光。`relight=True` 增加随世界法线朝向变化的受光衰减和实际几何的 Ambient Occlusion。`scene_analysis.lighting` 中的 `world_direction` 是指向主要光源的世界向量，`ambient_fraction` 控制环境光占比，`occlusion_distance` 以所跟踪平面宽度为单位。它是基于照片的近似重照明，尚不包含完整的直接投影、镜面反射和透射。大幅翻面或完整 PBR 需求使用实际模型和原生材质，并检查渲染结果。

生成的几何已处于跟踪世界坐标，调用它时设置 effect.placement 的 center_uv=[0.5,0.5]、size=1、local_origin=[0,0,0]、depth=0，避免二次变换。context.camera_data 可读取 K、原相机和逐帧跟踪记录。

## 坐标与放置

默认场景坐标为被选平面的局部坐标，X 向右、Y 向上、Z 朝向平面前方。平面宽 1，高度由 plane.aspect 决定，原点位于平面中心。导入的完整相机也使用 Blender 世界到相机约定。

场景中的顶层几何会归入一个 CG volume，effect.placement 控制其在被选面中的位置。

- center_uv 是锚点在平面中的位置，左上为 [0,0]，右下为 [1,1]。
- size 控制整体模型尺寸，以所选面宽度为单位。
- depth 让几何离开被选面，正值朝平面前方。
- rotation_degrees 调整模型方向，例如将台面上的物体转为站立。
- local_origin 指定模型中哪个局部点与锚点重合，自定义场景默认为 [0,0,0]。

位置、旋转和缩放保存在原生 Blender 工程中。多层级模型只挂接顶层节点，骨骼与子物体关系会保留。

执行刚体、布料或粒子模拟前，根据本片世界坐标和真实地面确定重力方向。相机对齐后的局部 Y/Z 不一定对应 Blender 默认的世界向上方向，碰撞网格的存在也不代表模拟已经运行。

## 跟踪与遮挡

固定摄像机适合实际稳定的镜头。平面模式从素材中取得特征和位姿。完整三维解算可以由 Blender 等工具产生相机 JSON，字段包括 width、height、fps、K、frames，每个 frame 包含从零开始的 frame 和一个 4×4 camera_matrix。矩阵采用 Blender camera.matrix_world，当前导入要求去畸变、方形像素和零 skew。原相机偏心通过 K 的主点处理。

foreground_mask 接受静态图片或与本片从零起点对齐的遮罩视频。白色区域保留实拍前景，使其挡住后面的CG；黑色区域使用正常合成。需要双向遮挡、反射或落地阴影时，根据本片几何在 Blender 中添加对应代理和渲染通道，并实际核对遮挡结果。

## 验证

先看核心动作时刻的静帧，再看起始、交互和收尾。要确认它真的位于目标表面或空间中，模型的透视、反射、光照、运动模糊和遮挡相互一致。framehash、跟踪误差和解码成功只能覆盖部分质量指标。
