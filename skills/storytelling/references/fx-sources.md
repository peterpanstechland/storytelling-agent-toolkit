# Effect-source catalog (open-source survey, 2026-10)

Which open-source effect / shader / transition projects were evaluated for autocut, what their licence allows, and what was done with them.
Policy: only MIT / BSD / Apache-2.0 / CC0 / ISC / Zlib-class sources may be **ported or bundled** (with attribution in `NOTICE.md` and the effect's docs).
GPL / AGPL / CC-BY-NC / CC-BY-SA / source-available / unlicensed projects are **reference only**: nothing is copied, nothing is vendored; where an effect idea is
re-implemented it is written from scratch from the public technique, and says so. Stars / push dates are from the GitHub API on 2026-10-16; licences from the repository's
declared licence and README/LICENSE (re-check before relying on them — they change).

## Ported or implemented in autocut

| Source | Stars · last push | Licence | What it is | autocut mapping | Status |
|---|---|---|---|---|---|
| [mrsarac/ff-tracking](https://github.com/mrsarac/ff-tracking) | 432 · 2026-10-14 | MIT | Virtual camera films an agent's terminal; tracker boxes lock on glyphs; LED/thermal lens look | `tracker_hud`, `lens_look`, `terminal_hud` clip type, HUD SFX, style `tracker_hud` | **Ported** (NumPy re-implementation of the look/technique; its Rust/Skia generator is not embedded) |
| [gl-transitions/gl-transitions](https://github.com/gl-transitions/gl-transitions) | 2151 · 2026-10-15 | MIT per collection; each transition file carries its own author + `License:` header (125 transitions: 123 MIT, 1 BSD-3, 1 BSD-2 at the time of the check) | The open GLSL transition collection | 13 transitions → `gl_*` custom transitions (`vcut/fx/gltransitions.py`) | **Ported** (credits below) |
| Ashima Arts / Ian McEwan simplex noise (embedded in `luminance_melt`) | – | MIT | 2-D simplex noise | used inside `gl_luma_melt` | **Ported** (as part of that transition) |
| Film emulation / halation / split-tone (technique; cf. [JanLohse/spectral_film_lut](https://github.com/JanLohse/spectral_film_lut) 112★ MIT, [raw2film](https://github.com/JanLohse/raw2film) 32★ MIT) | – | MIT (references) | Datasheet-based film LUT generator | `film_stock` effect + styles `premium_film`/`premium_maker` | **Original implementation** (no code copied; credit as inspiration). To use real datasheet LUTs, generate a `.cube` with spectral_film_lut yourself and set `color.lut` |
| Anamorphic streak flare (technique) | – | – | Horizontal highlight stretch | `anamorphic` effect | **Original implementation** |
| Analogue-video artefacts (technique; cf. ntsc-rs below) | – | – | Chroma smear, ghosting, head wobble, dropouts | `vhs_pro` effect | **Original implementation** |

### GL Transitions included (all `// License: MIT`, re-implemented from the GLSL)

| autocut name | Original | Author | Cost (CPU, 720p / frame) | Note |
|---|---|---|---|---|
| `gl_cross_zoom` | CrossZoom | rectalogic | ~65 ms | half-res, 12 jittered taps instead of 41 |
| `gl_crosswarp` | crosswarp | Eke Péter | ~50 ms | |
| `gl_directional_warp` | directionalwarp | pschroen | ~40 ms | |
| `gl_ripple` | ripple | gre | ~30 ms | |
| `gl_morph` | morph | paniq | ~60 ms | |
| `gl_overexposure` | Overexposure | Ben Zhang | ~12 ms | |
| `gl_dreamy_zoom` | DreamyZoom | Zeh Fernando | ~20 ms | keeps the original's `DEG2RAD` constant |
| `gl_swirl` | Swirl | Sergey Kosarevsky | ~50 ms | |
| `gl_fly_eye` | flyeye | gre | ~55 ms | |
| `gl_cube` | cube | gre | ~70 ms | |
| `gl_glitch_displace` | GlitchDisplace | Matt DesLauriers | ~65 ms | dead voronoi code in the GLSL dropped |
| `gl_film_burn` | FilmBurn | Anastasia Dunbar | ~60 ms | light field at ¼ res, 12-tap radial blur at ½ res |
| `gl_luma_melt` | luminance_melt | 0gust1 | ~15 ms | Ashima simplex noise |

Transitions last 0.5–0.9 s, so the cost is a few seconds of extra render time per project. 1080p is ≈2.3× the 720p numbers.

## Evaluated, not ported (candidates for later)

| Repo | Stars · last push | Licence | What / why not (yet) |
|---|---|---|---|
| [scriptituk/xfade-easing](https://github.com/scriptituk/xfade-easing) | 124 · 2026-09-09 | MIT | GL Transitions + CSS easings as ffmpeg `xfade` expressions. Good if we ever want GPU-free *ffmpeg-only* transitions; our NumPy ports already cover the visually best ones. **Next candidate** for more transitions (e.g. wind, burn, doorway) |
| [mifi/editly](https://github.com/mifi/editly) | 5526 · 2025-05-12 | MIT | Node + headless GL editing tool using gl-transitions. Node/GL runtime, different architecture; no code to port beyond gl-transitions itself |
| [transitive-bullshit/ffmpeg-gl-transition](https://github.com/transitive-bullshit/ffmpeg-gl-transition), [ffmpeg-concat](https://github.com/transitive-bullshit/ffmpeg-concat) | 720 / 989 | no LICENSE file detected by GitHub (package metadata says MIT) | Needs a custom ffmpeg build with OpenGL — not portable to Windows/CPU users; licence file missing → reference only |
| [ntsc-rs/ntsc-rs](https://github.com/ntsc-rs/ntsc-rs) | 2659 · 2026-10-15 | Core crates + plugins MIT / ISC / Apache-2.0 (GUI GPL-3.0) | Best VHS/NTSC simulator. Rust; porting the signal model is a larger job. Could be used as an **external tool** (separate process) in the future. `vhs_pro` is an independent, simpler effect |
| [JanLohse/spectral_film_lut](https://github.com/JanLohse/spectral_film_lut) | 112 · 2026-10-15 | MIT | Generates real film-stock LUTs. Run it yourself and feed a `.cube` to `color.lut` (supported already); bundling the generated LUTs not done (size, stock names/trademarks) |
| [JanLohse/raw2film](https://github.com/JanLohse/raw2film) | 32 · 2026-10-15 | MIT | Raw editor with film emulation (halation, grain). Idea source only |
| [scernst13/HaldCLUT-Cube-Files](https://github.com/scernst13/HaldCLUT-Cube-Files) | 6 · 2026-02-22 | CC0-1.0 declared | Provenance unclear (re-export of popular HaldCLUTs whose originals are not CC0) → **not bundled** |
| [motion-canvas/motion-canvas](https://github.com/motion-canvas/motion-canvas) | 19348 · 2026-07-02 | MIT | TypeScript animation editor. Different runtime; useful for explainer animation, not per-frame footage FX |
| [ManimCommunity/manim](https://github.com/ManimCommunity/manim), [3b1b/manim](https://github.com/3b1b/manim) | 41570 / 95125 | MIT | Maths animation; out of scope for footage polish |
| [airbnb/lottie-web](https://github.com/airbnb/lottie-web) | 32238 · 2025-09-01 | MIT | Lottie/AE JSON renderer (browser). Could render lower-thirds/stickers via headless browser; not built. Individual Lottie files have their own licences |
| [dragoon0x/typo](https://github.com/dragoon0x/typo) | 0 · 2026-03-14 | MIT | 76 web text effects (React). Tiny/unvetted; autocut already has `typewriter/kinetic/highlight_box/...` |
| [evanw/glfx.js](https://github.com/evanw/glfx.js) | 3456 · 2023-10-23 | MIT | WebGL image effects (zoom blur, swirl, bulge…). Techniques already covered (zoom blur via `gl_cross_zoom`) |
| [mattdesl/glsl-film-grain](https://github.com/mattdesl/glsl-film-grain) | 210 · 2016-03-11 | MIT | Grain function; `film_stock`/`grain` already do luma-weighted grain |
| [Zulko/moviepy](https://github.com/Zulko/moviepy) | 14989 · 2026-08-26 | MIT | Python editing library. We use ffmpeg + NumPy directly |
| [GuanYixuan/pyJianYingDraft](https://github.com/GuanYixuan/pyJianYingDraft) | 4573 · 2026-10-14 | Apache-2.0 | Already the 剪映 backend (`draft`). Its metadata enums (`TransitionType`, `FilterType`, `VideoSceneEffectType`…) are the **authoritative list of 剪映 effect names** autocut maps to (`autocut jy-effects`); 剪映's own assets/VIP effects are not redistributed |
| [Luci0n/CrowFX-Unity-Image-Effects](https://github.com/Luci0n/CrowFX-Unity-Image-Effects) (8★), [AlexMerzlikin/Unity-VHS-Shader](https://github.com/AlexMerzlikin/Unity-VHS-Shader) (15★), [Niviento/NVTO-Reshade-Shaderpack](https://github.com/Niviento/NVTO-Reshade-Shaderpack) (0★) | small | MIT | Unity/ReShade shaders for CRT/VHS/film/glitch. Small, engine-specific; ideas only |
| [tomastimelock/video-fx](https://github.com/tomastimelock/video-fx) (150 named effects), [cut-fx](https://github.com/tomastimelock/cut-fx) (559 transitions) | 0 / 1 · 2026-05 | MIT | Very new, ~no usage, unvetted provenance of the bulk catalogue → not ported (not inspected in depth) |
| [bloc97/Anime4K](https://github.com/bloc97/Anime4K) | 21514 · 2024-08-17 | MIT | Upscaler for anime; not a look/transition |
| [mrdoob/three.js](https://github.com/mrdoob/three.js) post-processing (glitch/film/bokeh passes) | 116466 | MIT | GLSL passes we could port later (Bokeh, Film, Glitch). JS/GL runtime; techniques already covered by `lens_look` DoF / `film_stock` / `glitch` |

## Rejected (licence or fitness) — reference only, do not copy

| Repo / family | Licence | Why rejected |
|---|---|---|
| Shadertoy shaders in general | Default CC BY-NC-SA 3.0 unless the author states otherwise | Non-commercial + share-alike. Only shaders that explicitly carry MIT/CC0 would qualify (none ported) |
| [patriciogonzalezvivo/lygia](https://github.com/patriciogonzalezvivo/lygia) | Prosperity (non-commercial) / Patron licence | Non-commercial for general use |
| [remotion-dev/remotion](https://github.com/remotion-dev/remotion) | Remotion License (source-available; company licence for larger orgs) | Not OSI-permissive; React runtime anyway |
| [animate-css/animate.css](https://github.com/animate-css/animate.css) | Hippocratic License | Not permissive; CSS only |
| [cedeber/hald-clut](https://github.com/cedeber/hald-clut) | GPL-3.0 | Copyleft |
| [libretro/glsl-shaders](https://github.com/libretro/glsl-shaders) | mixed per shader (GPL/LGPL/public domain) | Per-file licensing, much GPL |
| [NatronGitHub/clut](https://github.com/NatronGitHub/clut) | no licence | Unlicensed |
| [MMehdiMousavi/AnamorphicSim](https://github.com/MMehdiMousavi/AnamorphicSim) | no licence | Unlicensed (technique re-implemented from scratch) |
| [MushroomFleet/DJZ-Nodes](https://github.com/MushroomFleet/DJZ-Nodes) | no licence | Unlicensed |
| [spite/Wagner](https://github.com/spite/Wagner) | not detected | Unverified |
| [pmndrs/postprocessing](https://github.com/pmndrs/postprocessing) | Zlib | Permissive, but three.js-only; nothing needed beyond what we have (not rejected on licence) |
| ntsc-rs standalone GUI | GPL-3.0 | Copyleft (the core crates are permissive, see above) |
| Frei0r / many ffmpeg plugin packs, Natron, most AE-preset marketplaces, 剪映/CapCut built-in effects | GPL / proprietary | Not redistributable; 剪映 effects can only be *referenced by name* in drafts |

## Re-checking
`gh api repos/<owner>/<repo>` (licence, stars, pushed_at) and the LICENSE file; for GL Transitions read the header of the transition's own `.glsl` file — the collection licence is not enough.
