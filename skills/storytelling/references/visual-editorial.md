# Illustrated editorial and visual delivery

Read this for image cards, photo overlays, diagrams, long-image articles, GIF inserts and motion graphics. Prefer actual relevant material over decorative stock imagery. Build generated illustration assets only when they improve the explanation, and distinguish illustration from observed evidence.

## Design information around the thing being explained

Use an establishing image to orient the audience, then zoom into one meaningful relationship. A photograph plus a small anchored overlay often explains more than a large number on an empty card. Show what a joint tracker follows on a visible body; explain sampling rate with a short timeline or sequential positions. Do not scatter dots at arbitrary anatomical locations and call them model output.

Overlays should have a coordinate and time reference. Track labels to the correct subject; use leader lines when an offset improves legibility. If calibration or tracking is illustrative, describe it as a schematic rather than a measurement. Keep foreground people, the ball, readable signage and evidence visible. A heatmap requires a stated quantity and scale; decorative particles are not heat values.

Use hierarchy sparingly: one primary question/claim, one supporting visual, and a short interpretation. Build rhythm across a sequence using a full-bleed image, a tightly cropped detail, a comparison, a simple diagram and a quiet sentence. Avoid repeating identical dashboard cards for an entire article. Maintain consistent type sizes, alignment, contrast and author/brand roles across variations.

## Motion must reveal something

A scan can reveal tracked landmarks; a trajectory can explain timing; a camera move can expose an occluded relation; a matched movement can connect real footage to a diagram. A still image that only enlarges and shrinks is not a reconstructed replay. Do not label procedural particles “3DGS/4DGS reconstruction” unless the scene really uses that representation and its reconstruction evidence is available.

Choose duration around the time required to understand the revealed relationship. For an explanatory GIF, keep one concept per loop and include a short hold before resetting. Avoid rapidly flashing text, abrupt illegible loops and effects that hide the decisive action. Use [video-production.md](video-production.md) for compositing, camera and grade details.

## Long-image and GIF articles

Create a mobile-width editorial composition, then slice at intentional section boundaries. Keep a figure with its caption and source; avoid a cut through a face, headline or sentence. Separate animated inserts from static slices so a platform does not flatten the animation. A GIF has no sound: narration/music belong in an optional video or the platform's supported audio feature. Avoid implying an image article can autoplay a soundtrack everywhere.

Retain editable HTML/JSON/source and a text version for accessibility, search and later corrections. Do not make an entire explanatory article available only as tiny rasterized text. Check the narrowest actual reading view and export sizes after compression; publication constraints change, so confirm the current uploader instead of treating memorized dimensions or size limits as permanent rules.

The optional [capture_web.mjs](../scripts/capture_web.mjs) helper captures locally authored pages; [motion-scene.html](../templates/motion-scene.html) provides a deterministic motion scene. Read [web-capture.md](web-capture.md) and inspect the helper's `--help` before use. These are rendering tools, not evidence generators or proof of platform acceptance.

## Pixel-art illustrations

When an icon, character, diagram or looping insert should be pixel art, use the sibling [pxl](../../pxl/SKILL.md) skill. It renders PNG, GIF and sprite-sheet JSON from a `.px.js` file with Node ≥ 22.18 and no runtime install. Write that source and its `--out` directory in the user's project, not into the skill folder.

Copy a finished PNG into the card JSON directory before using it as a `photo-overlay` image, or attach it as an article figure. A GIF can be the animated insert described above; it has no soundtrack. Call the result an illustration unless the pixels are the user's own observed art. Reference images next to [CREDITS.md](../../pxl/examples/tropical/refs/CREDITS.md) are CC-BY; keep that credit if you reuse them.

## Portable card renderer

Run from the skill directory (the folder containing `SKILL.md`), including when this folder has been copied into another agent's skills directory:

```sh
python scripts/render_cards.py examples/cards.json --output /tmp/story-cards
```

Requires Pillow. Pass `--font /path/to/font.ttf` or `.ttc` for a specific font. Chinese text requires a font with the relevant glyphs (for example, Noto Sans CJK installed by the operating system). Fonts and image assets are not bundled. The script discovers an installed font and gives an actionable error if required CJK glyphs are unavailable; visually inspect other scripts/emoji with an appropriate font.

The output contains numbered-by-ID PNG files, `index.html` for local preview and `manifest.json` recording dimensions and measured text boxes. It does not upload anything. Existing files are protected. `--force` replaces only named files owned by the previous renderer manifest; unrelated files are retained. Use a fresh output directory for each review version.

The JSON contract is independent of the story brief described in [brief-contract.md](brief-contract.md):

```json
{
  "version": 1,
  "title": "Preview title",
  "author": "Author credit",
  "defaults": {"width": 1080, "height": 1440, "accent": "#64d8ee"},
  "cards": [{
    "id": "01-opening",
    "layout": "cover",
    "eyebrow": "SERIES / TOPIC",
    "title": "A useful audience question",
    "body": "A short explanation with a concrete reason to continue.",
    "footnote": "Optional source or author credit",
    "alt": "Description of the card for the preview and handoff"
  }]
}
```

Common fields: `id`, `layout`, `title`, optional `eyebrow`, `body`, `footnote`, `alt`. Override `width`, `height`, `background`, `foreground`, `muted`, `accent` per card or in `defaults`; colors use six-digit hex. IDs are safe filename stems. Dimensions are 320–8192 pixels, subject to 32 megapixels per card and 128 megapixels per batch. These bounds protect local rendering resources; they are not platform upload limits.

Layouts:

- `cover`: title and body with geometric decoration. Suitable for an opening question.
- `photo-overlay`: additionally requires `image`, a path **relative to and inside the JSON directory**. Optional `image_focus: [0.5, 0.5]` controls the crop focus from 0 to 1. It crops to fill and applies a dark gradient; inspect faces and labels after cropping.
- `stat`: requires `value`, `meaning`, `source`. Put the unit in `value`, the scope/interpretation in `meaning`, and provenance in `source`. The renderer does not validate whether a claim is true and does not compute statistics.
- `quote`: the quote goes in `title`; use `attribution` for the speaker/source. Do not use quotation styling to invent a real person's statement.
- `process`: requires 2–5 `nodes`, each with `title` and optional `body`. This is a sequence of steps, not a general node-link graph.

Text wraps using measured glyph widths. Font sizes shrink within readable layout bounds, then rendering fails with the card ID if copy still overflows. Shorten, split or resize the card instead of hiding text or forcing unreadably small type. Mixed dimensions are supported; a landscape variant may require shorter copy rather than blindly reusing portrait text. The example spec uses explicitly fictional content and cannot serve as a real project report without replacing it with verified material.

## Review exported pixels

Check image/subject identity, photo crops, sources, numbers and units, font coverage, margins, long words, line breaks, arrow direction, author/brand separation and small-screen reading. Then inspect the actual PNG/GIF/MP4 and the intended uploader preview. A successful render or a machine-readable manifest alone does not prove editorial or visual correctness.
