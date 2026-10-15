# Auto edit: camera moves, effects and 360° reframing

Overview and workflow: [auto edit](auto-edit.md). Shot language and delivery checks: [cinematic language](cinematic-language.md). `autocut` below means
`python3 video/run autocut`.

autocut has a **frame-level engine** (FFmpeg decode → NumPy/OpenCV per frame → FFmpeg encode). Everything it does is visible in the `autocut render` MP4 and, where
possible, mapped into the 剪映 draft. A **style** decides *what and how strongly*; the planner (LLM or offline rules) decides *where*:

| Where | Rule |
|---|---|
| Music beats / downbeats | beat punch-in, beat shake, downbeat white flash (never on talking heads) |
| Section changes | the style's section transition (whip / spin / zoom-through / glitch / light leak…) + a short effect + riser→hit SFX |
| Action peaks | analysis records each shot's frame-difference peak (`activity` / `peak_t`); there the planner adds a speed ramp, a freeze + callout or speed lines |
| 360 footage | planet→normal opening, orbit / tiny planet / crystal ball for establishing shots, invisible-selfie-stick hero for selfies, follow by default; whip between consecutive 360 clips |
| Talking heads | only a slow push or subject framing; no flashy effects. Maker projects may add a demo picture-in-picture |

## Styles (`autocut styles`)

| id | Name | Move/effect palette | Transitions | 剪映 filter |
|---|---|---|---|---|
| `beat_max` | 极致卡点 (beat max) | punch every beat, downbeat flash, beat shake, speed ramps, speed lines/flares | whip, spin, zoom-through, flash | 高清4K电影 |
| `cyber_glitch` | 赛博科技/故障 | RGB split, block glitch, scanlines, vignette, punch every other beat, freeze + callout, PIP | glitch, whip, zoom-through | 赛博朋克 |
| `cinematic_360` | 电影感 360 | tiny-planet opening, smooth follow, orbit, hero shot, crystal ball; grain + glow + leaks/flares; 2.35 letterbox | light leak, whip, zoom-through | 青橙电影 |
| `film_retro` | 胶片复古 | film grain + gate weave, vignette, leaks, VHS segments, typewriter subtitles | light leak, flash | 港风 |
| `warm_daily` | 温暖日常 | gentle push/pull, slight handheld feel, soft glow, occasional leak | dissolve | 日系奶油 |
| `tech_minimal`, `energetic`, `cinematic` | earlier styles | extended with the same palette keys (tech minimal has the progress bar on) | | |

A style file holds: `motion` (intensity 0–1, moves allowed per shot category, punch/ramp/freeze/pip probabilities, 360 move table), `fx` (global look, section/peak
effects, flashes), `sfx`, `text_anims`, `progress`, `jianying` (filter / intro / text animation / scene-effect names). Copy a style and change `id` to make your own;
look up 剪映 names with `autocut jy-effects --free -s keyword`.

## 360° footage (Insta360 X5)

- **Recommended input**: a **2:1 panorama MP4** exported from Insta360 Studio (stabilization + horizon leveling on, H.265, 5.7K 30 fps) → `autocut ingest`. A video
  that is at least 1920 wide and 2:1 is flagged `projection: equirect` (device recorded as X5); keyframes are stored as a front/back pair of flat views for the vision model.
- **Moves** (`autocut fx` lists everything): `follow` track the subject, `orbit` panning loop, `hero` invisible-selfie-stick third person, `whip360` rotational whip with
  motion blur, `tiny_planet`, `planet_intro` (tiny planet → normal view, for openings), `rabbit_hole`, `crystal_ball`, `fixed360`. All work in 16:9 and 9:16 (the field of
  view is computed from the long side, so vertical output keeps its framing).
- **Subject tracking**: YOLO ONNX (`track.yolo_model`, needs `onnxruntime`; weights are not shipped, mind their license) → YuNet faces (`autocut models fetch yunet`) →
  Haar/HOG (OpenCV 4 only) → motion → fixed heading. Results are Gaussian-smoothed and turn-rate limited (`track.max_slew_deg`) so the camera does not whip around.
- **Try one move without a project**: `autocut preview /path/to/equirect.mp4 --move hero --aspect 9:16 --dur 6`.
- **Raw `.insv`**: `autocut x5-stitch file.insv` stitches an emergency 2:1 panorama with the ffmpeg `v360` dual-fisheye filter. Honest caveats: no FlowState stabilization,
  no gyro horizon leveling, no seam blending, no per-unit lens calibration (default FOV 193°), parallax errors near the seam, and the X5 lens order/orientation is **not verified
  against a real file** (only a synthetic panorama → fake dual-fisheye → stitched-back round trip was checked). Use `--preview-only` first and `--swap` / `--back-rot180` / `--roll`
  if needed. Use Insta360 Studio (or the official Media SDK) for a real film.

> Why not animate with `v360`: verified on FFmpeg 8.1, `v360` yaw/pitch/roll/fov can be changed at run time with `sendcmd`, but commands are cumulative (they need
> `reset_rot`), per-frame commands tear (the two halves of one frame can have different orientation) and 720p ran at about 19 fps. The built-in reprojector does all
> animation (general perspective `r=(d+1)sinθ/(d+cosθ)`: d=0 rectilinear, d=1 tiny planet, d>1 crystal ball; animating d + fov + pitch gives planet→normal). `v360` is used only
> for static dual-fisheye stitching and PIP views.

## Flat footage: moves, effects, transitions, text

- **Moves** (`clip.move`): `push_in` / `pull_out` (eased), `pan` / `tilt` (crop window), `roll` (auto-zoomed to hide corners), `subject` (subject-aware framing, used for
  landscape→portrait); `punch` (fx, follows `edl.beats`), `shake` (fx, optionally on beats). **Speed** `ramp`: any profile, smooth easing, `interp: blend` (frame blend) / `flow`
  (ffmpeg minterpolate) / `nearest`. **Freeze** `freeze`: white flash + pop card + tilt + shadow, optional text. **Picture-in-picture / split** `pip`: `pip_br/bl/tr/tl`,
  `split_lr/tb`; a 360 source used as a small window is converted to a flat view automatically.
- **Effects** (`clip.fx` windows, or `edl.look` for the whole film): `glitch` (RGB split + block displacement + scanlines), `rgb_split`, `scanlines`, `light_leak` (procedural),
  `flare`, `flash`, `speed_lines`, `grain` (film grain + gate weave), `vhs`, `motion_blur`, `glow`, `vignette`, `bw`.
- **Custom transitions** (rendered per frame): `whip_left/right/up/down` (directional motion blur), `spin` / `spin_ccw`, `zoom_through` (3D push + radial blur), `glitch`, `flash`,
  `light_leak`. The usual xfade transitions still work.
- **Text animation** (`overlay.anim` or style `text_anims`): `fade`, `pop`, `slide_up`, `typewriter`, `glitch`, `stamp`, `kinetic` (word-by-word / two-character groups),
  `highlight_box`; `callout` overlays draw a leader line and target ring; `edl.progress` adds a bottom progress bar with chapter ticks.
- **SFX** (`audio[].kind = sfx`): transition whoosh/swish, section riser→hit, flash hit, glitch, freeze shutter, pop. `settings.yaml → sfx.library` can point at a local library
  with subfolders `whoosh/ hit/ riser/ glitch/ shutter/ pop/ swish/`; missing categories are synthesized (no third-party audio is included).

Hand-tuning means editing `edl.json`, for example:

```json
{"id": "c007", "move": {"type": "orbit", "params": {"turns": 1, "direction": "left"}},
 "projection": "equirect",
 "fx": [{"type": "glitch", "start": 0.0, "dur": 0.4, "intensity": 0.9},
        {"type": "punch", "intensity": 0.8, "params": {"every": 2}}],
 "ramp": {"profile": [[0, 1.0], [0.4, 0.3], [0.7, 0.3], [1, 1.8]], "interp": "blend"},
 "freeze": {"at": 1.2, "hold": 1.0, "text": "look here"},
 "transition_in": {"type": "whip_left", "duration": 0.35}}
```

## Performance

- Clips with moves or effects use the frame engine; other clips keep the fast ffmpeg path. Each clip is rendered to a **cached intermediate** (key includes source, parameters,
  engine version), so changing captions/music/SFX only redoes the final assembly.
- Clips render in parallel; NVENC (h264_nvenc / hevc_nvenc) is used automatically, and `x5-stitch` switches to hevc_nvenc above 4096 px wide.
- Reference (8-core CPU, no GPU, libx264): a 59 s 1080p showcase (21 clips, all through the engine, including 5.7K→2880 panorama reprojection) took about 2.5 minutes the first
  time and about 45 s to re-render after a text change.
- `autocut render --quick` renders at half resolution; `--no-fx` or `render.fx: false` turns the frame engine off. `render.equirect_width` (default 5760) sets the panorama
  decode width; lower it to 3840 on slow machines.

## Showcase

`python3 video/autocut/scripts/make_showcase.py ./work/showcase` renders `showcase_16x9.mp4` (≤60 s, covering every 360 move, flat move, effect, transition, text animation,
picture-in-picture and SFX), `showcase_9x16.mp4` and a keyframe contact sheet `showcase_contact.jpg` from procedurally generated media (a synthetic 2:1 panorama, flat views projected
from it, a Mandelbrot clip and a synthetic drum loop). Output goes to a directory you choose; nothing is committed.

## Sources and licenses

The effects, reprojection and SFX synthesis are this repository's own code (MIT). Third-party dependencies and their licenses are listed in the repository's `NOTICE.md`; no YOLO
weights are distributed.
