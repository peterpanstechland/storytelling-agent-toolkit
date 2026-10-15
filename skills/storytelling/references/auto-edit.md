# Auto edit (autocut): project-based footage management, styled rough cuts and 剪映 drafts

Use this reference when there is a lot of footage from several devices (360, action cam, phone, glasses) and the user wants a **shot list, missing-shot
reminders, footage understanding and a styled rough cut**, exported as an MP4 preview or a **剪映 (Jianying) draft** for finishing. For a few clips with
decided cuts, use `render` from [video production](video-production.md). Shot language and delivery checks stay in
[cinematic language](cinematic-language.md); this page covers how the tools connect. Camera moves, effects and 360 details are in
[auto edit: moves and effects](auto-edit-effects.md).

The tool's own output (CLI messages, styles, subtitles, config comments) is Simplified Chinese because it was built for Chinese-language creators; the
commands and file formats below are language-neutral.

## How it divides work with the existing video tools

| Step | Tool | Notes |
|---|---|---|
| Media index, contact sheets | `run inspect` | autocut can ingest the `manifest.json` it writes |
| Speech recognition | `run transcribe` (local faster-whisper) | import the result with `autocut import-transcript` so autocut does not transcribe again; or set `asr.engine: toolkit` so autocut calls the same script |
| Simple edit → `master.mp4`, bilingual subtitles | `run render` + edit.json v1 | source-clock captions, frame-exact cuts, no transitions/moves/effects |
| Narration assembly, mixing | `run narrate` / `run mix` | `autocut import-narration` adds the narration track and subtitles to the EDL |
| **Assets by project type, device detection, shot list, gap reminders** | `run autocut` | project-based, see below |
| **Shot detection, vision understanding, styled EDL planning** | `run autocut` | optional cloud/local vision model; offline heuristics without one |
| **Camera moves, effects, 360, SFX, 剪映 draft** | `run autocut` | one frame-level engine; the MP4 preview and the draft correspond |

autocut is a **project-level planner**; `render` is a **small deterministic renderer**. They meet through files and do not depend on each other: without the
autocut dependencies every existing toolkit command behaves exactly as before.

## Install and launch

autocut lives in `video/autocut/` and ships with the skill; there is nothing to install as a package. Install its extra dependencies into your own environment:

```sh
python3 -m pip install -r video/requirements-autocut.txt           # required: typer, rich, pyyaml, pydantic, httpx, numpy, OpenCV
python3 -m pip install -r video/requirements-autocut-optional.txt  # optional: 剪映 export, PySceneDetect, beat detection, YOLO tracking
python3 -m pip install -r video/requirements-asr.txt               # optional: transcription (shared with the toolkit)
python3 video/run doctor --require autocut                         # overall capabilities including autocut
python3 video/run autocut doctor                                   # autocut details: encoders, detector, whether API keys are set
```

Commands are `python3 video/run autocut <command>`; this page writes `autocut <command>`. `autocut --help` lists them all. Without any optional package the flow
`new → shotlist → ingest → analyze → plan → render` still completes; a missing piece only degrades that feature (no ASR → no talking-head detection, no
pyJianYingDraft → no draft, no vision model → offline classification).

Configuration is in `video/autocut/config/`: `settings.yaml` (backends, ASR, render, tracking, SFX, music library, 剪映 folder), `devices.yaml`, `styles/`, `types/`.
Put personal changes in `settings.local.yaml` next to it (only the keys you override; git-ignored) or point `VCUT_CONFIG_DIR` at your own directory; do not
edit the shipped defaults. **Credentials only come from environment variables** (`DASHSCOPE_API_KEY`, `GEMINI_API_KEY`). Nothing is downloaded unless you run
`autocut models fetch yunet` (a 230 KB face-detection model) or your ASR/vision backend does so.

## Project types

| Type | Purpose | Default structure |
|---|---|---|
| `event` | exhibitions, meetups, launches | arrival → on-camera opening → atmosphere → people → closing |
| `sponsored` | brand collaborations | must-show shots, key messages, forbidden items, logo position and CTA live under `sponsor:` in `project.yaml`; missing must-shoot shots are flagged |
| `maker` | hardware/software project films | pain point → project → build → features (each entry of `maker.features` becomes a shot and a caption title) → closing |
| `vlog` | daily life / travel | opening → journey → details → reflection |

Templates are `config/types/*.yaml` and can be copied and adapted. Each section has a duration ratio, allowed shot categories and a selection mode (speech / best
picture / chronological / must-show).

## Workflow

```sh
autocut new "ESP32 lamp" --type maker --duration 90           # create the project; edit project.yaml: theme, features, platforms, style
autocut shotlist "ESP32 lamp"                                  # before shooting: shotlist.md
# …shoot…
autocut ingest "ESP32 lamp" /path/to/cards /path/to/exports    # --mode link/ref avoids copying large files
autocut analyze "ESP32 lamp"                                   # shots, quality, transcript, vision (incremental cache)
autocut gaps "ESP32 lamp"                                      # what is still missing
autocut plan "ESP32 lamp"                                      # edl.json + edl.md
autocut render "ESP32 lamp" --quick                            # half-resolution preview first; drop --quick for the full render
autocut draft "ESP32 lamp"                                     # 剪映 draft + FCPXML + SRT
```

`autocut run <project>` chains analyze → gaps → plan → render → draft. Every step can be re-run on its own; analysis and intermediate clips are cached.

### Shot list and gap reminders

`shotlist` builds a list from the project type, theme, feature list and **the devices actually available**: each shot has a name, category, suggested device,
minimum length, required flag and shooting hint, plus pre-shoot preparation (battery, frame rate, audio, per-device notes). With a vision/text backend the model
adds shots specific to the theme; without one the template is used. `gaps` compares the list with the **analyzed footage** and reports required shots that are
missing or too short (`analysis/gaps.md`). It tells you whether footage of that kind exists; it does not judge whether the story works.

### Device detection

`ingest` identifies the camera from `devices.yaml` using metadata keywords, manufacturer, filename patterns, extension and (as a hint) resolution; the most specific
match wins. The result drives shot-list recommendations and 360 handling. Default entries: Insta360 X5, Ace Pro 2, GO Ultra, **Ray-Ban Meta glasses** (container
`comment` contains `device=Ray-Ban Meta Smart Glasses`, vertical 1392×1872), iPhone, a generic Android phone, and an ordinary config entry as an example of a single
device (HONOR Robot Phone). When detection is uncertain, run `autocut probe clip.mp4` to see the real metadata and add the keyword to `tags:`; set
`available: false` for a borrowed device after returning it so it is no longer recommended. `devices.yaml` is a user-editable config; never commit serial numbers or
other personal identifiers to it.

### Footage understanding

`analyze` does three things: shot detection (ffmpeg scene filter, or PySceneDetect when installed), quality and motion (blur, shake, frame-difference peaks) and
transcription. Vision understanding can use `dashscope` (Alibaba Cloud Model Studio), `gemini`, `ollama` (local) or `none` (offline heuristics): only keyframes
downscaled to 512 px are sent, one or two per shot, batched and cached. The model proposes category, description, tags and a highlight score. **That is a model's
reading of the picture, not verification**: people, brands and numbers still need the identity and source checks from [video production](video-production.md).
Manual labels go in `analysis/labels.yaml` (highest priority) or `autocut tag`.

### Planning and styles

`plan` writes `edl.json` (the edit decision list): clips, in/out points, transitions, camera moves, effects, subtitles, titles, SFX and music. Without an AI backend a
rule-based planner picks by the template's section ratios, speech sentence boundaries, quality and highlight scores, and snaps cuts to the music beats; with a backend
the model proposes the plan, which is validated (unknown transition/move/effect names are dropped) and falls back to the rule plan on failure. **Re-running `plan`
overwrites manual edits**; earlier versions are kept in `analysis/edl_history/`. For hand adjustments edit `edl.json` and only re-run `render` / `draft`.

Styles (`autocut styles`): `beat_max`, `cyber_glitch`, `cinematic_360`, `film_retro`, `warm_daily`, `tech_minimal`, `energetic`, `cinematic`. A style defines the
palette and intensity of grade, transitions, moves, effects, SFX, text animation and 剪映 item names. The style decides *what and how strongly*; the planner decides
*where*: punch-ins and flashes land on beats and never on talking heads, section changes get the style's section transition plus sound, and action peaks get a slow-down,
freeze or speed lines. Do not let every shot carry the same effect; restraint is tuned with `motion.intensity` and related keys (see
[cinematic language](cinematic-language.md)).

### Rendering and outputs

`render` writes an MP4 preview (and SRT) into `renders/` with an incrementing version; it never overwrites. Clips with moves or effects go through a frame-level
engine (CPU, per frame, slower than plain ffmpeg: roughly 1–3 minutes per output minute on 8 cores; clips are cached, so changing captions/music/SFX re-renders in
seconds); other clips use the fast ffmpeg path. NVENC is used when available. `--quick` is half resolution; `--no-fx` disables the frame engine. Always look at the
actual frames: automated checks do not replace review.

## Connecting to the other toolkit commands

```sh
# toolkit → autocut
python3 video/run inspect ./media --out ./work/index-v1
autocut import-index  "project" ./work/index-v1/manifest.json     # ingest indexed videos (references original paths, no copy)
python3 video/run transcribe ./media/talk.mp4 --model ./models/asr --out ./work/talk.json
autocut import-transcript "project" talk.mp4 ./work/talk.json      # analyze reuses it instead of transcribing again
autocut import-edit "project" ./work/edit-v1.json                  # an existing edit.json becomes an EDL, ready for styles / 剪映 export

# autocut → toolkit
autocut export-edit "project" --out ./work/edit-from-autocut.json  # EDL → edit.json v1
python3 video/run render ./work/edit-from-autocut.json --out ./outputs/visual-v2
python3 video/run narrate ./work/narration-v1.json --out ./outputs/voice-v1
autocut import-narration "project" ./outputs/voice-v1              # narration track + subtitles into the EDL; music ducking turned on
```

**`export-edit` is lossy.** edit.json v1 has straight cuts, source-clock captions and one music bed. Transitions, moves, effects, speed curves, freezes,
picture-in-picture, title text, SFX tracks and ducking are dropped, and the command lists each dropped item. 360 clips would render as the raw 2:1 picture, so export
a flat MP4 first. Use `autocut render` for the full result. Subtitle times are mapped back to source time and clamped to their clip's in/out. Likewise `import-edit`
produces an EDL without moves or effects (add them by hand, or `autocut plan`, which replaces the imported result); only the Chinese caption slot is imported when a
cue has both languages.

## 360 footage and 剪映 drafts

- **Insta360 X5 / 2:1 panoramas**: export a **2:1 panorama MP4** from Insta360 Studio (stabilization and horizon leveling on). `ingest` flags it as 360 and the planner
  picks tiny-planet openings, follow, orbit, invisible-selfie-stick and whip moves, in 16:9 or 9:16. Details: [moves and effects](auto-edit-effects.md).
- **Raw `.insv`**: `autocut x5-stitch` can stitch an emergency panorama with ffmpeg `v360`. It has **no stabilization, no horizon leveling, no seam blending, and the
  lens order/orientation has not been verified against a real X5 file**; check with `--preview-only` first. Use Studio or the official SDK for a real film.
- **剪映 draft**: `draft` writes cuts, speed, transitions, subtitles, music, narration and logo into a 剪映 draft; camera moves become keyframes, effects become 剪映
  scene effects and the style grade becomes a 剪映 filter. What 剪映 cannot express (360 reframing, speed curves, freezes, picture-in-picture) is pre-rendered into
  motion-only clips under `drafts/jianying_media/`. Names are checked against the installed pyJianYingDraft, free items are preferred, and every item used (with its VIP
  flag) is listed in `vcut_说明.txt` in the draft folder. A draft is an **approximation**; the preview MP4 is the reference. 剪映 updates can change the draft format;
  open the draft in the app before relying on it. Set the 剪映 folder with `jianying.drafts_dir` or `VCUT_JIANYING_DRAFTS` (on Windows it is found automatically).

## Honest limits

- The frame engine is per-frame CPU work and slow for long films; use `--quick`, and `--no-fx` if needed. Procedural leaks, glitches and flares are stylized
  approximations, not real optical footage.
- Subject tracking tries YOLO ONNX → YuNet faces → motion → fixed heading. OpenCV 5 has no Haar/HOG. YOLO weights are not shipped; choose one and respect its
  license (Ultralytics YOLOv8/11 weights are AGPL-3.0). The synthetic test footage has no faces, so automated tests exercise only the motion path; the YOLO path has
  never run with a real model.
- Vision-model descriptions, categories and highlight scores are guesses; they can misread objects or treat a bystander as the subject. Cloud backends send
  downscaled keyframes to a third party; use local `ollama` or `none` for private or confidential footage.
- Automatic SFX are synthesized placeholders (you can point to a library you are licensed to use); music must be licensed by the user. Beat detection is better with
  librosa installed and falls back to a simple algorithm without it.
- FCPXML carries cuts, average speed and transitions only. 10-bit/HLG/Log footage is converted to 8-bit without tone mapping; convert HDR to SDR properly first.
- The rule planner produces a **reviewable rough cut**, not a finished film. Narrative, facts, identity, brand and rights still follow the rest of this skill.
- Not verified against a real X5 `.insv`, real Ray-Ban Meta clips, the real 剪映 client or real cloud models (automated tests use only synthetic media and mocked HTTP).
