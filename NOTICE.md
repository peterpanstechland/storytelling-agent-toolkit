# Scope of the license

The toolkit's authored code, instructions and text examples are MIT licensed. The
video workflow is adapted from the author's `maker-video-agent` tools. No source
footage, participant photographs, voice recordings/clones, music recordings,
third-party logos, downloaded models or platform credentials are distributed.

## pxl

[`skills/pxl`](skills/pxl) is a vendored copy of
[peterpanstechland/claude-pxl](https://github.com/peterpanstechland/claude-pxl)
at commit `72b9b8cdb9fccb7ec40472871aedc8f6153c09de`. That repository is Peter's
fork of [augusto-scarvalho/claude-pxl](https://github.com/augusto-scarvalho/claude-pxl),
which is a fork of [crsolver/claude-pxl](https://github.com/crsolver/claude-pxl).
The pxl program, guides and examples written for pxl are MIT licensed. The
copyright notice is [skills/pxl/LICENSE](skills/pxl/LICENSE) (Copyright (c) 2026
crsolver). Keep that notice with any copy of the skill.

[skills/pxl/examples/tropical/refs/](skills/pxl/examples/tropical/refs) is
third-party pixel art under CC-BY 4.0. The credits also record earlier CC-BY
3.0, OGA-BY 3.0 and GPL 3.0 works those sheets are based on. Those images are
not relicensed as MIT. Credit the authors named in
[CREDITS.md](skills/pxl/examples/tropical/refs/CREDITS.md) and
[CREDITS-jungle.txt](skills/pxl/examples/tropical/refs/CREDITS-jungle.txt) when
reusing the images or the trees reduced from them.

Gallery GIFs and PNGs under [skills/pxl/docs/](skills/pxl/docs) are generated
example output from the upstream project. They stay in the tree so the skill
docs and `test/gallery.test.ts` match that commit. They are not user footage.

Python, FFmpeg, Pillow, Playwright, faster-whisper, voice/video models and any
other optional engines keep their own licenses. Installing or invoking one does
not relicense it under MIT. No model weights or upstream model implementation
are bundled here. Brand/platform names identify destinations and technologies;
this toolkit is not an official product of those services.

## Code-video material ported into this tree

Only MIT text and a small timing/pose adaptation were copied. The survey, including
repositories that were not copied, is `skills/storytelling/references/fx-sources.md`.
GPL, CC-BY, CC-BY-NC, source-available, unlicensed and Zlib-licensed shader code
was not copied. Grain, bloom, vignette and the title-card particle layer in
`skills/storytelling/codevideo/looks.py` are original.

| Source | Included | Left upstream |
|---|---|---|
| [lemomo-ai/lemo-opuscar](https://github.com/lemomo-ai/lemo-opuscar) @ `b5e8ef93930b6d828f352055a689320f138237b1` | 51 `STYLE.md` briefs and `style.json` files under `codevideo/styles/lemo/`. MIT. Copyright (c) 2026 LemoLab | Demo films, posters, fonts, 3D assets, audio, the upstream renderer |
| [Vincentwei1021/mg-styles-15](https://github.com/Vincentwei1021/mg-styles-15) @ `49052d80bfaf9fa8412cc9710530e5e95a3b8d8c` | 15 motion-graphics prompts, `template.md`, `rubric.md`. MIT. Copyright (c) 2026 Vincentwei1021 | Films, screenshots, audio samples, demo source |
| [mexicat/pdoom-video](https://github.com/mexicat/pdoom-video) | Word timing, syllable progress, curly quotes and ASS karaoke export in `codevideo/lyrics.py`. MIT. Copyright (c) 2026 Giacomo Magnanini | The song, audio, lyric files, scenes and WebGL engine |
| [JohnHeibel/ClaudeAnimationBase](https://github.com/JohnHeibel/ClaudeAnimationBase) | Beat clock, 31 emotion poses, dances and shot lookup in `codevideo/performance.js`. MIT. Copyright (c) 2026 John Heibel | The Clawd drawing, p5.js, p5.brush, model sheets and the demo scene. The figure in `templates/character-beat.html` is an original geometric stand-in |
| [yihui-dev/awesome-opus5-5-videos](https://github.com/yihui-dev/awesome-opus5-5-videos) @ `92aee2f586ac0715cb3cbcb6384834f98a33383d` | Index metadata only (`codevideo/opus-index.json`): category, tags, author, post URL, prompt-file URL. MIT. Copyright (c) 2026 yihui-dev | Prompt bodies. Those posts remain the original authors' text; open the upstream file |

These MIT portions keep their upstream copyright. The MIT permission text is the
same notice at the top of this repository's LICENSE. Using the tools does not
relicense upstream projects, and it does not grant rights in songs, fonts,
posters or model weights that were not copied here.

代码成片的中文取舍表见 `skills/storytelling/references/fx-sources.md`。

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

### 并入 autocut 的上游特效工作（均为 MIT，必须保留署名）

| 来源 | 并入内容 | 许可与署名 |
|---|---|---|
| [mrsarac/ff-tracking](https://github.com/mrsarac/ff-tracking) | `tracker_hud`、`lens_look`、`terminal_hud` 插卡与对应音效的 NumPy 重新实现（镜头透视/景深/色散/调色板/LED 网格/追踪框外观与时序） | MIT，Copyright (c) 2026 Mustafa Saraç。本仓库只含重新实现的代码，不含其 Rust/Skia 源码或渲染结果；改动见 `references/auto-edit-effects.md` |
| [GL Transitions](https://github.com/gl-transitions/gl-transitions) | 13 个转场的 NumPy 重新实现（`vcut/fx/gltransitions.py`）：CrossZoom（rectalogic）、crosswarp（Eke Péter）、directionalwarp（pschroen）、ripple（gre）、morph（paniq）、Overexposure（Ben Zhang）、DreamyZoom（Zeh Fernando）、Swirl（Sergey Kosarevsky）、flyeye（gre）、cube（gre）、GlitchDisplace（Matt DesLauriers）、FilmBurn（Anastasia Dunbar）、luminance_melt（0gust1） | 各转场文件头声明 `License: MIT`，版权归各自作者与 GL Transitions 贡献者；luminance_melt 内含 Ashima Arts / Ian McEwan 的 simplex noise（MIT） |
| 其他（`film_stock`、`anamorphic`、`vhs_pro`） | 本仓库原创实现，仅参考公开的技术描述；未复制任何第三方代码 | MIT（本仓库） |

调研过的其余开源特效项目及其许可结论（采用 / 仅供参考 / 拒绝及原因）见 `skills/storytelling/references/fx-sources.md`。
GPL、AGPL、CC-BY-NC、source-available 与无许可证的项目只作参考，没有复制其代码。Pillow（HPND/MIT-CMU）为可选依赖，用于 HUD 文字。

云端视觉/文本后端（阿里云百炼、Google Gemini）和本地 Ollama 模型只在使用者配置了密钥或服务时调用，
各自的服务条款与模型许可由使用者负责；会把缩小的关键帧发送到所选服务。自动音效为程序合成，
不含第三方音频；配乐必须是使用者有授权的音乐。设备预设（Insta360、Ray-Ban Meta 等）只是识别用的关键字，
品牌名仅用于指明设备，本工具包不是这些厂商的官方产品。

Creators retain responsibility for the material they choose to publish. The
fictional examples are for exercising the tools and are not real event reports
or measured technical claims.
