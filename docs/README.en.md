# Storytelling Agent Toolkit

A portable AI-agent skill and working utilities for evidence-grounded stories:
illustrated articles, social carousels, narrated edits, motion graphics and
platform handoff. MIT licensed; created from the author's real editorial work.
No source footage, voices, logos, music recordings, model weights or credentials
are included. The pxl skill vendors its example gallery and CC-BY reference
sprites; see [NOTICE.md](../NOTICE.md).

Start with [SKILL.md](../skills/storytelling/SKILL.md). The entire
`skills/storytelling` directory is self-contained and can be copied into any
compatible agent's skill directory. [pxl](../skills/pxl/SKILL.md) is a second
skill for pixel-art PNG, GIF and sprite-sheet output. Agents without skill
discovery can read either file as ordinary instructions. Host-specific tool
names are not required; the host supplies research, image generation, TTS,
browser and account tools.

```bash
python3 scripts/install_skill.py --target ~/.codex/skills
python3 scripts/install_skill.py --skill pxl --target ~/.codex/skills
```

The installer copies the selected skill only. The default is storytelling.
`--skill all` copies both. It stops when the destination already exists.

## Run locally

Python 3.10+ is required. Install Pillow for cards/contact sheets and system
FFmpeg/FFprobe for editing/audio. CJK content requires an installed CJK font.
ASR and Playwright/Chromium are optional.

```bash
python3 skills/storytelling/scripts/story.py init /tmp/story-demo --demo
python3 skills/storytelling/scripts/story.py validate /tmp/story-demo/brief.json
python3 skills/storytelling/scripts/story.py pack /tmp/story-demo/brief.json --output /tmp/story-demo/pack
python3 skills/storytelling/scripts/render_cards.py skills/storytelling/examples/cards.json --output /tmp/story-demo/cards
python3 skills/storytelling/video/run doctor
# optional auto-edit package (needs: python3 -m pip install -r skills/storytelling/video/requirements-autocut.txt)
python3 skills/storytelling/video/run doctor --require autocut
python3 skills/storytelling/video/run autocut --help
```

These examples are explicitly fictional. The brief tool exports local channel
files; it does not generate prose through an API or publish anything. The agent
authors the story and channel variants, and selects the user's source material.

## Implemented versus integrated

- Real PNG card rendering, overflow/font checks and HTML preview.
- Local article/metadata/thread/video-description packages for ten format
  variants across the requested destinations.
- FFmpeg cuts, contact sheets, optional local ASR, bilingual subtitle outputs,
  narration assembly, ambience/music mixing and ducking.
- Deterministic local web-artwork capture to PNG slices, MP4 or GIF. A working
  Canvas motion template is included; Three.js/GSAP scenes can implement the
  same `window.renderFrame(seconds)` contract. Code-film style briefs, karaoke
  timing and a beat-locked character page are documented in the code-video guide.

- WeChat Official Account API adapter: local preview, body/cover uploads,
  draft creation/readback, explicit publication submission and status checks.
- Browser/connector handoff guides for Xiaohongshu, CSDN, AWS Builder Center, X,
  WeChat Channels, Douyin, Bilibili and YouTube. Their upload APIs are **not**
  implemented by this package.
- **Auto edit (`video/run autocut`)**: project-based management of multi-device
  footage (event / sponsored / maker / vlog projects), device detection from
  editable config (Insta360 X5, Ace Pro 2, GO Ultra, Ray-Ban Meta glasses,
  phones), shot lists and missing-shot reminders, shot detection and optional
  vision-model understanding (DashScope / Gemini / Ollama, or fully offline
  heuristics), styled rough cuts with beat-synced punch-ins, whip pans, speed
  ramps, glitch/leak/flash effects, kinetic text and synthesized SFX, **Insta360
  X5 360° auto-reframing** (tiny planet, orbit, follow, hero shot; 16:9 and 9:16),
  FFmpeg MP4 preview and **Jianying (剪映) draft** export. Also: ff-tracking-style tracker HUD / lens look / terminal card (MIT port), 13 ported GL Transitions, film emulation / anamorphic streaks / VHS Pro and the `premium_film` / `premium_maker` styles (sources and licence verdicts: `skills/storytelling/references/fx-sources.md`). It converts to and
  from the toolkit's `edit.json`, transcripts, inspect index and narration
  output (the `edit.json` export is lossy). It needs extra packages
  (`video/requirements-autocut.txt`); every other command works without them.
  Jianying drafts are approximations, raw `.insv` stitching is an emergency
  fallback, and the 360/Jianying/cloud-model paths have not been verified against
  real devices or services. See [auto edit](../skills/storytelling/references/auto-edit.md).
- Voice cloning/TTS providers remain external choices. Narration tools assemble
  already generated or recorded audio; no voice model is bundled.
- Pixel-art PNG, GIF and sprite sheets from the vendored [pxl](../skills/pxl/SKILL.md)
  skill. Card renderers and the video edit plan consume those files; pxl does
  not call them.

The [publishing guide](../skills/storytelling/references/publishing.md) records
official sources and verification limits. Platform changes require checking the
current editor/API, rather than relying on fixed limits in a skill. Uploading,
drafting, moderation, public publication and follower broadcasts are distinct.
Use existing human authorization, and verify remote receipts before claiming
success.

## Pixel art (pxl)

[skills/pxl](../skills/pxl/SKILL.md) is vendored from
[peterpanstechland/claude-pxl](https://github.com/peterpanstechland/claude-pxl)
commit `72b9b8cdb9fccb7ec40472871aedc8f6153c09de`. That repository is Peter's
fork of [augusto-scarvalho/claude-pxl](https://github.com/augusto-scarvalho/claude-pxl),
itself a fork of MIT-licensed
[crsolver/claude-pxl](https://github.com/crsolver/claude-pxl). Node ≥ 22.18,
no runtime dependencies.

```bash
node skills/pxl/bin/pxl.js build skills/pxl/examples/shop.px.js --no-preview --out /tmp/pxl-shop
```

Write `--out` into the user's project. A PNG can be a card `photo-overlay`
image or an article figure. A GIF with a finite ffprobe duration can be a
video clip (title card or short insert). A still PNG is not a clip. Sprite-sheet
JSON stays with the sheet; the edit plan has no overlay track. Tropical
reference PNGs are CC-BY. See [NOTICE.md](../NOTICE.md).

```bash
cd skills/pxl && npm ci && npm run check
```

## Project discipline

Keep author, featured people and brand identity separate; do not put another
presenter's close-up under “I built this.” Every metric needs a meaning and
scope. Distinguish measured tracking, illustrative particles and trained
Gaussian reconstruction. For a local revision preserve the accepted edit and
audio outside the requested change.

Keep production sources and credentials outside the toolkit. The release
scanner checks tracked files for private media, common secrets, private
machine paths and broken documentation links. Upstream example art under
`skills/pxl` is the exception recorded in NOTICE.md. Tests generate temporary
media and mock network responses; they never publish to live accounts.

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
python3 scripts/check_release.py --tracked
```

[Main Chinese documentation](../README.md) · [License](../LICENSE) ·
[Third-party boundaries](../NOTICE.md)
