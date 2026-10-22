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

Creators retain responsibility for the material they choose to publish. The
fictional examples are for exercising the tools and are not real event reports
or measured technical claims.
