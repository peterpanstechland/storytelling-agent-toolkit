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

Creators retain responsibility for the material they choose to publish. The
fictional examples are for exercising the tools and are not real event reports
or measured technical claims.
