# Accepted-film revisions and channel variants

Use this route for a narrow change after the user has accepted an edit. Start
from the named baseline edition, preserve its cut clock, narration and music
unless the user also requested those changes, and export a separately named
version. Do not silently substitute a later channel-specific edition.

## Color-only revision

A gray-looking shot may need exposure/contrast recovery, a camera-specific Log
transform, or undoing an inappropriate earlier look. Inspect metadata and a
representative frame first; do not stack an arbitrary LUT over every shot. When
an earlier grade crushed skin tones, return to the pre-look source/proxy and
match the exact in/out/crop, then reapply an approved grade. Never transfer a
neighboring version's entire picture just because its speaker looks brighter.

The portable `grade` command covers the simpler **SDR brightness recovery** case:

```bash
python video/run grade /path/to/grade.json --out /path/to/outputs/film-color-v2
```

Start from [grade.json](../video/examples/grade.json). Use an existing zero-origin,
constant-frame-rate, 8-bit `yuv420p` SDR master; HDR and variable-frame-rate input
are rejected rather than silently reinterpreted. Plan paths are relative to the
JSON. Each shot has half-open `start`/`end` seconds, a pixel `region` expressed as
`[x, y, width, height]`, `lift` (−0.2 to 0.3) and `saturation` (0.5 to 1.5). Entries
must be ordered and nonoverlapping. Regions have even coordinates/dimensions for
4:2:0 sampling. Omit `region` only when the whole image should be graded.

The lift curve raises midtones while anchoring black/white endpoints. It is a
creative curve, **not** a camera Log-to-Rec.709 transform or substitute for a
technical LUT. Crop the grading region to the footage area when titles, logos,
subtitles or graphic backgrounds should keep their approved colors. For arbitrary
masks, transitions crossing differently exposed sources, or true LUT transforms,
use the original compositor/grade pipeline and retain the checks below.

`graded.mp4` is promoted only after a full decode, matching frame count and all
frame timestamps, and matching encoded-audio packet hashes. Audio is stream
copied. Optional `.srt`/`.ass`/`.vtt` sidecars are copied unchanged. Outside the
chosen regions, pixels bypass the grade, but the final video is re-encoded so
compression can change decoded values. The manifest records these limits.

Compare before/after frames at each affected shot's beginning, middle and end,
plus adjacent cuts and an unchanged control shot. Check skin tones, shadow detail,
clipped highlights and dark stage backgrounds. Do not turn a dark venue into a
flat gray frame just to raise average brightness. Keep these proof images private.

## Replace restricted material throughout a channel edition

A platform restriction belongs to that edition's brief; do not assume it applies
to every platform or that replacing material guarantees publication approval.
Inventory **all appearances** of the restricted content, including:

- Full-screen footage and slow-motion/replay/3D inserts that retain original pixels.
- Intro montages, computer/phone screens, screenshots and product-demo windows.
- Reflections, projected/background screens, thumbnail collages and freeze frames.
- Both source handles inside transitions, end cards, cover images and GIF exports.

Replace the corresponding timeline slots with relevant authored diagrams,
virtual scenes, UI demonstrations or permitted event details. A token blur or
particle treatment over the same match footage is not a fully virtual replacement.
For a synthetic scene, keep editorial claims tied to the source analysis and
identify illustrative geometry when it is not a measured reconstruction. Check
brand/celebrity exclusions in nested screens too, at the prominence threshold the
user requested; do not invent a universal prohibition.

Vary explanatory form with the story: a spatial orbit for defensive position,
a top-down court for movement, a temporal comparison for an evolving decision.
Repeatedly orbiting the same scene does not add information. Preserve accepted
section durations and audio whenever the change is picture-only. Review boundary
frames on either side of each cut and throughout crossfades, then inspect the full
export for leftovers. Keep the unrestricted baseline and platform variant separate.
