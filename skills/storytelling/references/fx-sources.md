# 代码成片与外部仓库目录（2026-10-22）

本文件记录这一轮对 18 个公开仓库的核对结果：仓库是否存在、GitHub 声明的许可证、以及对本工具包（叙事、图文卡片、代码成片、卡拉 OK 时间轴、角色表演）的决定。

许可政策：只有 MIT / BSD / Apache-2.0 / CC0 / ISC 可以**移植或收录代码与提示词正文**，并在 `NOTICE.md` 署名。GPL、CC-BY、CC-BY-NC、CC-BY-SA、source-available 和无许可证的仓库**只作参考**：不复制代码、不复制提示词、不收录样片。Zlib 不在上述允许清单里，因此也不复制。星标与 `pushed_at` 来自 2026-10-22 的 GitHub API；许可证以仓库的 license 字段和 LICENSE 文件为准，引用前应再核对一次。

本目录不依赖未合并的 autocut 分支。那里另有一份特效调研，合并时请把两份章节都留下。

## 并入

| 仓库 | 星标 · 最近推送 | 许可证 | 收录了什么 | 没有收录什么 |
|---|---|---|---|---|
| [lemomo-ai/lemo-opuscar](https://github.com/lemomo-ai/lemo-opuscar) @ `b5e8ef93` | 4911 · 2026-10-19 | MIT，Copyright (c) 2026 LemoLab | 51 个风格的 `style.json` 与 `STYLE.md`，外加写作模板。检索：`python codevideo/styles.py` | 样片、海报、字体、三维模型、音频、上游渲染器 |
| [Vincentwei1021/mg-styles-15](https://github.com/Vincentwei1021/mg-styles-15) @ `49052d80` | 1651 · 2026-10-05 | MIT，Copyright (c) 2026 Vincentwei1021 | 15 份动态图形提示词、`template.md`、`rubric.md` | 成片、截图、音频采样和 demo 源码 |
| [mexicat/pdoom-video](https://github.com/mexicat/pdoom-video) | 3162 · 2026-10-05 | MIT，Copyright (c) 2026 Giacomo Magnanini | 词级时间轴、音节进度、弯引号和 ASS `\k` 导出（`codevideo/lyrics.py`） | 歌曲、音频、歌词原文、场景与 WebGL 引擎 |
| [JohnHeibel/ClaudeAnimationBase](https://github.com/JohnHeibel/ClaudeAnimationBase) | 1493 · 2026-09-24 | MIT，Copyright (c) 2026 John Heibel | 节拍时钟、31 种表情姿态、舞蹈词汇、镜头查找（`codevideo/performance.js`） | Clawd 画法、p5.js / p5.brush、模型表图片、demo 场景。网页里的人偶是原创几何形 |
| [yihui-dev/awesome-opus5-5-videos](https://github.com/yihui-dev/awesome-opus5-5-videos) @ `92aee2f5` | 8489 · 2026-10-13 | MIT，Copyright (c) 2026 yihui-dev | 703 条索引：分类、技术标签、作者、帖子链接、上游提示词文件链接（`codevideo/opus-index.json`） | 提示词正文。合集文件超过本仓库单文件体积预算，且正文来自第三方帖子 |

用法见 [code video](code-video.md)。

## 仅参考

| 仓库 | 星标 · 最近推送 | 许可证 | 为什么不并入 |
|---|---|---|---|
| [VAST-AI-Research/TripoSR](https://github.com/VAST-AI-Research/TripoSR) | 7179 · 2026-06-04 | MIT，Copyright (c) 2024 Tripo AI & Stability AI | 单图重建三维模型。许可允许使用，但本工具包不捆绑模型权重和研究代码。故事需要道具网格时，在自己的环境里运行上游工具，并单独核对权重许可 |
| [pmndrs/drei](https://github.com/pmndrs/drei) | 10030 · 2026-10-21 | MIT | react-three-fiber 辅助库，体积大，绑定 React 运行时。做三维标题卡时可以读它的 Text / Environment 文档，不要整库搬进来 |
| [Alchemist0823/three.quarks](https://github.com/Alchemist0823/three.quarks) | 1107 · 2026-05-21 | MIT，Copyright (c) 2019 Forrest Sun | three.js 粒子引擎。`codevideo/looks.py` 里的粒子是原创的小图层，没有复制这里的发射器或着色器 |
| [pmndrs/react-postprocessing](https://github.com/pmndrs/react-postprocessing) | 1472 · 2026-10-21 | 包装层 MIT；效果本体在 [pmndrs/postprocessing](https://github.com/pmndrs/postprocessing)（Zlib） | Zlib 不在允许移植的清单里。光晕、颗粒、暗角是原创 Pillow 实现，没有复制其 GLSL |
| [JohnHeibel/PDoomVideo](https://github.com/JohnHeibel/PDoomVideo) | 2423 · 2026-09-25 | GitHub 未检测到 LICENSE，README 也没有许可证 | 同一首歌的另一版 MV。无许可证就不能复制。角色表演改从上面有 MIT 许可的 ClaudeAnimationBase 移植 |
| [athemeroy/awesome-claude-5-5-videos](https://github.com/athemeroy/awesome-claude-5-5-videos) | 669 · 2026-10-11 | CC-BY-4.0 | CC-BY-4.0 不在允许移植的清单里。它可以当工作流索引来读，不要把正文抄进本仓库 |
| [joeseesun/opus-video-prompts](https://github.com/joeseesun/opus-video-prompts) | 630 · 2026-09-27 | 无 LICENSE。README 写明提示词和成片版权归原作者，仓库只做索引 | 中文案例索引有用，但不能复制提示词。需要某条提示词时打开上游并遵守原作者的授权 |

## 跳过

这些仓库许可多为 MIT 或 Apache-2.0，许可不是拒绝原因。它们服务的是游戏引擎、编辑器或多人同步，不是叙事、图文或成片。

| 仓库 | 星标 · 最近推送 | 许可证 | 原因 |
|---|---|---|---|
| [gamedev-skills/awesome-gamedev-agent-skills](https://github.com/gamedev-skills/awesome-gamedev-agent-skills) | 2511 · 2026-10-09 | Apache-2.0 | 74 个技能是 Godot、Unity、Unreal、Phaser、pygame 等游戏开发路由，不是故事或视频技能 |
| [CoderGamester/mcp-unity](https://github.com/CoderGamester/mcp-unity) | 1983 · 2026-10-11 | MIT | Unity 编辑器 MCP |
| [Coding-Solo/godot-mcp](https://github.com/Coding-Solo/godot-mcp) | 6257 · 2026-04-16 | MIT | Godot 编辑器 MCP |
| [pmndrs/react-three-rapier](https://github.com/pmndrs/react-three-rapier) | 1507 · 2026-10-12 | MIT | Rapier 物理绑定，给游戏模拟用 |
| [Mugen87/yuka](https://github.com/Mugen87/yuka) | 1442 · 2026-10-20 | MIT | 游戏 AI（转向、状态机） |
| [colyseus/colyseus](https://github.com/colyseus/colyseus) | 7445 · 2026-10-21 | MIT | Node 多人游戏同步 |

## 再核对

`gh api repos/<owner>/<repo>` 看 `license`、`stargazers_count`、`pushed_at`，并打开仓库里的 LICENSE。合集仓库还要看它是否真的拥有提示词正文的版权。
