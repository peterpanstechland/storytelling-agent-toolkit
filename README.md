# Storytelling Agent Toolkit

**把真实素材变成有故事、有信息、有画面的内容，再交付到合适的平台。**

由「彼得潘的科技谷」的图文与视频制作实践整理。面向 AI Agent 的可移植 skill，加上能实际运行的图文、剪辑、声音装配和公众号工具。它保留创作方法与工程工具，**不包含活动素材、人物照片、声音样本、成片、品牌 Logo、模型或账号凭据**。

[Agent 入口：SKILL.md](skills/storytelling/SKILL.md) · [使用指南](docs/使用指南.md) · [English](docs/README.en.md) · [MIT License](LICENSE)

## 能做什么

- **叙事与文案**：从素材提炼问题、证据和转折；面向第一次了解主题的读者；技术科普、活动报道、项目故事、推广内容和平台版本。
- **图文与视觉**：照片叠加解释、数据图、长图切片、GIF、封面和轮播卡片。内置五种卡片版式，实际检查字体、换行和溢出。
- **视频**：素材索引、可选 ASR、FFmpeg 剪辑、中英字幕、旁白时间线装配、现场声音保留、配乐 ducking，以及局部修改后的版本检查。
- **自动剪辑（autocut）**：按项目管理多设备素材（活动/商单/Maker 项目/Vlog），设备识别、拍摄清单与缺镜头提醒、镜头切分与画面理解（可选云端或本地模型，也可纯离线）、带风格的整片粗剪；运镜、卡点、特效、自动音效、**Insta360 X5 360° 自动运镜**，输出 MP4 预览或**剪映草稿**。新增：ff-tracking 风格追踪框 HUD / 镜头质感 / 终端插卡（MIT 移植）、13 个 GL Transitions 转场、胶片模拟 / 变形拉丝光 / VHS Pro 与「高级感」风格（`premium_film`、`premium_maker`）；开源特效来源与许可结论见 [fx-sources](skills/storytelling/references/fx-sources.md)。可与上面的 `render` / `transcribe` / `narrate` 互相导入导出。
- **电影语言**：甩镜、突切、急推、节奏剪辑、对称构图、拖影、虚拟摄影机；八类片头、动态文字、VFX、LUT 与音画配合的制作指南。
- **程序化动效**：可复用 Canvas 动效模板；确定性网页逐帧渲染，可接 Three.js／SVG／GSAP 场景，导出 MP4 或 GIF。
- **发布助手**：把一个故事改编成不同平台的文案、媒体顺序和发布包；公众号提供实际 API 适配器，其他平台提供官方编辑器／连接器工作流。
- **像素画**：`skills/pxl` 用 `.px.js` 画出 PNG、精灵表和 GIF。图卡、文章配图、片头和短插入可以直接用这些文件。

发布目标包括微信公众号、小红书图文、CSDN、AWS Builder Center、X，以及微信视频号、小红书视频、抖音、B站和 YouTube。

这里的“支持平台”不是“内置了所有平台自动发文 API”。公众号支持上传、草稿与发布状态；其他平台需要 Agent 已连接的浏览器或官方连接器。**声音克隆也由选择的 TTS 提供方执行，工具包负责制作流程、音频装配与验证，不附带克隆模型。**

## 给 AI Agent 使用

不依赖特定品牌的 Agent。把以下任务交给具备文件和命令工具的 Agent 即可：

> 阅读 `skills/storytelling/SKILL.md`。根据我的素材制作一篇面向新读者的图文，以及一条两分钟的视频。先完成可预览版本，保留来源与素材身份记录；只准备我指定平台的发布包。

也可以把自包含的 skill 目录安装到你的 Agent 支持的 skills 目录。例如 Codex：

```bash
git clone https://github.com/peterpanstechland/storytelling-agent-toolkit.git
cd storytelling-agent-toolkit
python3 scripts/install_skill.py --target ~/.codex/skills
python3 scripts/install_skill.py --skill pxl --target ~/.codex/skills
```

默认只复制 `skills/storytelling/`。`--skill pxl` 复制像素画 skill，`--skill all` 两个都复制。安装器不修改全局模型、账号或其他 skill；目标已存在时停止。其他 Agent 选择其文档规定的目录，或直接读取对应的 `SKILL.md`。`agents/openai.yaml` 是 storytelling 的可选 UI 元数据，不是运行依赖。

## 五分钟本地试跑

基础工具使用 Python 3.10+。图卡需要 Pillow 和系统中文字体；视频需要 FFmpeg/FFprobe。模型和网页浏览器都是可选依赖。

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install Pillow

# 1. 纯文字虚构示例：不读取你的素材、不连接账号
python skills/storytelling/scripts/story.py init /tmp/my-story --demo
python skills/storytelling/scripts/story.py validate /tmp/my-story/brief.json
python skills/storytelling/scripts/story.py pack /tmp/my-story/brief.json --output /tmp/my-story/release-v1

# 2. 真正生成图卡 PNG、HTML 预览和清单
python skills/storytelling/scripts/render_cards.py skills/storytelling/examples/cards.json --output /tmp/my-story/cards-v1

# 3. 检查哪些视频能力在本机可用
python skills/storytelling/video/run doctor
```

示例中没有真实实验指标。将实际素材放在独立项目目录，填写 `brief.json` 的来源、画面身份和平台版本；通过 `asset_ids` 选择所需素材，`pack --copy-assets` 才会把选中的文件复制进**本地**发布包。它不执行网络上传。

未安装中文字体时，图卡工具会给出明确错误；可用 `--font` 指定有相应字形的字体。Linux 常用 Noto Sans CJK，字体不随仓库分发。

## 视频和声音

```bash
python skills/storytelling/video/run inspect /path/to/media --out /path/to/work/index-v1
python skills/storytelling/video/run render /path/to/edit.json --out /path/to/outputs/video-v1
python skills/storytelling/video/run narrate /path/to/narration.json --out /path/to/outputs/voice-v1
python skills/storytelling/video/run mix /path/to/mix.json --out /path/to/outputs/mix-v1
```

计划示例在 [video/examples](skills/storytelling/video/examples)。这些契约需要替换为自己的素材路径；不是附带成片的演示。`narrate` 装配录音或 TTS 已生成的声音，`mix` 保留画面流并混入旁白、现场声与音乐。字幕的源素材时钟与成片时钟分别说明，避免移镜头后字幕错位。

[完整视频指南](skills/storytelling/references/video-production.md) · [电影语言与 VFX](skills/storytelling/references/cinematic-language.md)

### 自动剪辑（多设备素材、风格化粗剪、360、剪映）

素材多、来自不同设备时，用项目制的 autocut（额外依赖需自己安装，其余命令不受影响）：

```bash
python -m pip install -r skills/storytelling/video/requirements-autocut.txt
python skills/storytelling/video/run doctor --require autocut
python skills/storytelling/video/run autocut new "我的项目" --type maker --duration 90   # event / sponsored / maker / vlog
python skills/storytelling/video/run autocut shotlist "我的项目"                          # 拍之前：拍摄清单
python skills/storytelling/video/run autocut ingest "我的项目" /path/to/footage            # 设备识别（X5、Ace Pro 2、GO Ultra、Ray-Ban Meta、手机…）
python skills/storytelling/video/run autocut analyze "我的项目" && python skills/storytelling/video/run autocut gaps "我的项目"
python skills/storytelling/video/run autocut plan "我的项目" && python skills/storytelling/video/run autocut render "我的项目" --quick
python skills/storytelling/video/run autocut draft "我的项目"                             # 剪映草稿（需 requirements-autocut-optional.txt）
# 与 toolkit 互通：export-edit / import-edit / import-index / import-transcript / import-narration
```

内置 8 种风格（极致卡点、赛博故障、电影感 360、胶片复古、温暖日常等）。没有任何云端密钥也能离线跑完；剪映草稿是近似，360 的 `.insv` 拼接只是应急方案。
完整流程、限制和与 `render` 的分工见 [自动剪辑](skills/storytelling/references/auto-edit.md) 和 [运镜与特效](skills/storytelling/references/auto-edit-effects.md)。

## 网页动效、长图和 GIF

```bash
npm install
npx playwright install chromium
node skills/storytelling/scripts/capture_web.mjs \
  --input skills/storytelling/templates/motion-scene.html \
  --output /tmp/my-story/motion-v1 --mode video \
  --width 1280 --height 720 --seconds 6 --fps 24
```

网页提供 `window.renderFrame(seconds)`，便能按时间确定性导出。`--mode still` 导出完整长图，`slices` 导出有序切片，`gif` 导出无声 GIF。脚本只打开本地素材页，阻止联网资源，不接管登录中的浏览器。内置模板是概念动效，不是实测数据、人物跟踪或 3DGS 重建。

[网页渲染说明](skills/storytelling/references/web-capture.md)

## 代码成片

51 个 Lemo-Opuscar 风格说明、15 个动态图形提示词、卡拉 OK 词级时间轴，以及一套 31 个表情的节拍表演，已经按许可收进 skill。游戏引擎、无许可证提示词和 Zlib 着色器只保留链接。检索与导出：

```bash
python skills/storytelling/codevideo/styles.py find 水墨
python skills/storytelling/codevideo/karaoke.py skills/storytelling/codevideo/examples/lyrics.json --output /tmp/lyrics-v1
python skills/storytelling/codevideo/catalog.py --category explainer --tag canvas
```

角色页是 `skills/storytelling/templates/character-beat.html`，仍用上面的网页渲染导出。标题卡的颗粒、光晕和暗角是本仓库原创的 Pillow 处理，不是外部着色器的拷贝。来源与取舍见 [fx-sources](skills/storytelling/references/fx-sources.md) 和 [代码成片说明](skills/storytelling/references/code-video.md)。

## 像素画（pxl）

[skills/pxl](skills/pxl/SKILL.md) 是像素画 skill，来自 [peterpanstechland/claude-pxl](https://github.com/peterpanstechland/claude-pxl) `72b9b8c`（Peter 对 [augusto-scarvalho/claude-pxl](https://github.com/augusto-scarvalho/claude-pxl) 的 fork，上游是 MIT 的 [crsolver/claude-pxl](https://github.com/crsolver/claude-pxl)）。需要 Node ≥ 22.18，没有运行时依赖。写 `.px.js`，得到 PNG、精灵表加 JSON、GIF，以及本地实时预览。

```bash
node skills/pxl/bin/pxl.js build skills/pxl/examples/shop.px.js --no-preview --out /tmp/pxl-shop
cd skills/pxl && npm ci && npm run check
```

把 `--out` 指到用户的项目目录，不要写进 skill 自己的目录。PNG 可以放进图卡 JSON 目录，当作 `photo-overlay` 的 `image`，或当作文章配图。ffprobe 能读出时长的 GIF 可以当作视频计划里的一个 clip（片头或短插入）。静止 PNG 没有时长，不能直接当 clip；要定格就先做成短 GIF，或放进本地网页再用网页渲染导出。精灵表 JSON 留给游戏或后续合成，视频计划里没有单独的叠加轨。

热带森林示例里的参考 PNG 是 CC-BY，不是 MIT。复用时保留 [CREDITS.md](skills/pxl/examples/tropical/refs/CREDITS.md) 中的署名。许可边界见 [NOTICE.md](NOTICE.md)。

## 发布与账号

公众号工具默认只预览，远程操作必须明确选择：

```bash
python skills/storytelling/publishing/wechat.py --help
python skills/storytelling/publishing/wechat.py preview /path/to/article.json --preview-out /tmp/article-preview.html
# 配置好私有运行环境中的 WECHAT_APP_ID / WECHAT_APP_SECRET 后：
python skills/storytelling/publishing/wechat.py draft /path/to/article.json --execute
# 仅在用户已经授权该草稿公开发布时：
python skills/storytelling/publishing/wechat.py publish DRAFT_MEDIA_ID --execute --authorized
```

正式执行前需要上传封面及正文图片，并把返回的 ID／URL 填入正文；完整流程见[发布指南](skills/storytelling/references/publishing.md)。回执按账号和内容去重，未知结果先核对，不盲目重发。保存草稿、提交审核、公开可访问和群发不是同一状态。

其他平台的入口、所需素材和实际支持范围见 [platforms.json](skills/storytelling/publishing/platforms.json)。不在代码中固化会变化的标题长度、图片数量、时长或 API 额度。

## 验证与贡献

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
python3 scripts/check_release.py
# Git 仓库中确认最终将提交的内容：
python3 scripts/check_release.py --tracked
```

测试覆盖图卡溢出、身份与数据引用、真实 FFmpeg 画面和音频边界、混音、公众号模拟 API、重复提交、发布状态和代码包检查，以及 autocut 的设备识别、规划、特效引擎、360 重投影、剪映导出和与 toolkit 的互通（未安装 autocut 依赖时这部分自动跳过）。测试只使用临时合成素材或模拟传输，不发布到真实账号。自动测试不能取代最终画面和声音审看。pxl 的类型检查和测试在 `skills/pxl` 里单独跑（`npm run check`，Node ≥ 22.18）；CI 用独立的 Node 任务，不替换上面的 Python 任务。发布检查仍拒绝私人素材；`skills/pxl` 里上游自带的示例图是唯一例外，说明见 [NOTICE.md](NOTICE.md)。

贡献新平台时写清楚它是实际适配器还是编辑器交接流程，并附测试与官方来源。贡献新特效时提供确定性时间接口和真实可导出的短样例。不要提交私人项目目录、账号文件、素材、声音或模型。
