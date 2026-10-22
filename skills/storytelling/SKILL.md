---
name: storytelling
description: Turn source material into evidence-grounded illustrated articles, social posts, image carousels and narrated videos, then prepare or publish the requested platform edition. Use for end-to-end storytelling and revisions, including footage editing, project-based auto-editing of multi-device footage (shot lists, gap reminders, styled rough cuts, 360 camera moves, Jianying drafts), graphics, narration and creator-platform handoff.
---

# Storytelling

Act as an editor and maker: deliver the actual article, images, video or requested platform result. A shot list or prompt list alone is not a finished production. This skill works with filesystem/shell tools and whichever research, image, voice, browser or platform tools the host agent actually has; it does not require a particular agent vendor.

## Start from the current assignment

Identify the intended audience, central question, source material, destination and finished format from the conversation. Preserve corrections across revisions; a new instruction about one shot does not reopen the whole film. Ask only for missing information that blocks useful work. Keep source originals intact and write new versions into the user's project.

Read only the relevant route:

- Narrative, research and scripts: [story design](references/story-design.md).
- Illustrated prose, overlays, long images, GIFs and carousels: [visual editorial](references/visual-editorial.md). Pixel-art sprites, scenes, sheets and GIFs come from the sibling skill [pxl](../pxl/SKILL.md); use its PNG and GIF files as card art, article figures, or a video title card or insert.
- Adapt one story for different audiences/channels: [adaptation](references/adaptation.md).
- Footage, narration, authorized voice cloning, subtitles and audio: [video production](references/video-production.md).
- Many clips from several devices, a shot list before shooting, missing-shot reminders, a styled rough cut with camera moves/effects, 360 footage or a 剪映 draft: [auto edit](references/auto-edit.md) (details of moves and effects: [moves and effects](references/auto-edit-effects.md); effect-source licences: [fx-sources](references/fx-sources.md)). For a handful of clips with decided cuts, use `render` from the video guide instead.
- Local expressive voice generation and ASR-backed checking: [voice cloning](references/voice-cloning.md).
- Color-only changes or replacement of restricted footage in a platform edition: [video revisions](references/video-revisions.md).
- Shot language, cinematic openings, motion graphics, VFX and color: [cinematic language](references/cinematic-language.md).
- A film built in code, a motion-graphics style, karaoke word timing or a beat-locked character: [code video](references/code-video.md). Surveyed repositories and what was copied: [fx sources](references/fx-sources.md).
- Upload, draft, publish and verify: [publishing](references/publishing.md).
- Structured briefs and local platform bundles: [brief contract](references/brief-contract.md).

## Preserve meaning while changing form

Introduce the topic for readers with no prior context. Numbers need a nearby meaning, population, period and unit; a normalized index is not automatically a probability. Keep observed footage, sourced measurements, hypothetical examples and artistic effects distinct. Do not fabricate missing metrics to make graphics look richer. Explain what the evidence reveals, not merely how the image was produced.

Keep author identity, featured people, brand and subject separate. A first-person line over another person's close-up can falsely attribute identity or testimony. Confirm who the shot represents, or use a short location/event cutaway and show the project or author during first-person speech. Treat background portraits/screens as part of the frame when a brief excludes celebrities or brands. Brand removal/localization rules are project settings, not universal defaults.

Use the user's chosen visual personality without making every moment the same effect: a cut, freeze/annotation, comparison, diagram, spatial move and quiet detail can each serve a different idea. Align words, measurements, gestures, narration and effects on the same timeline. A single-depth-image orbit is not trained 3D/4D Gaussian splatting; describe the method actually used. Store production bookkeeping outside audience copy, while preserving essential source credit and interpretation.

## Portable tools

Commands below are relative to this skill folder. Run `--help` before an unfamiliar operation.

- `python scripts/story.py init <project> [--demo]`: create a brief, never upload.
- `python scripts/story.py validate <brief.json> [--check-files]`: check structure and evidence/identity references; it cannot certify factual truth.
- `python scripts/story.py pack <brief.json> --output <new-directory> [--copy-assets]`: prepare selected channel files. Master text is marked as needing adaptation unless the agent authored a channel variant.
- `python scripts/render_cards.py <cards.json> --output <new-directory>`: render actual PNG cards with measured text layout; requires Pillow and a suitable font.
- `node scripts/capture_web.mjs ...`: optional local-page screenshots, long-image slices and deterministic web-animation export. See its `--help` and [web capture](references/web-capture.md). `templates/character-beat.html` is a beat-locked character page.
- `python codevideo/styles.py find <query>`: search vendored code-film and motion-graphics briefs. `python codevideo/karaoke.py <lyrics.json> --output <new-directory>` writes karaoke cues and an ASS file from timings you supply. `python codevideo/looks.py <image> --output <new.png>` grades a title card. `python codevideo/catalog.py` filters the external code-video index. Details and licences: [code video](references/code-video.md).
- `python video/run doctor`: inspect video capabilities (`--require autocut` for the auto-edit package). Use `inspect`, `transcribe`, `render`, `clone`, `voice-check`, `grade`, `narrate`, `mix` as described in the video guide. Models are selected externally, not included.
- `python video/run autocut --help`: project-based auto edit (`new`, `shotlist`, `ingest`, `analyze`, `gaps`, `plan`, `render`, `draft`, `preview`, `x5-stitch`) plus bridges to the tools above (`export-edit`, `import-edit`, `import-index`, `import-transcript`, `import-narration`). Needs `video/requirements-autocut.txt`; the other commands do not. Its plans are reviewable rough cuts: story, identity, brand and fact checks still follow this skill.
- `python publishing/wechat.py --help`: official-account API adapter. Local preview, remote media upload, draft creation and publication are separate operations.

No footage, voice samples, music, model weights, official logos, platform sessions or API keys ship with this skill. Text-only examples are demonstrations. Obtain project assets and credentials through the user's authorized environment. Use a host's native image/voice generation tools when available; do not claim a provider is installed simply because the guide mentions it.

## Verify and deliver

Inspect rendered media, not just the generating code. Check mobile legibility, line wrapping, cropped heads, visible brand/people, source meaning and each changed cut. Compare narration against actual audio, not an assumed duration; distinguish measured checks from subjective listening. Keep original speech intact when requested. For a narrow picture correction preserve accepted audio and timing, and compare audio hashes when copying the stream.

A local publishing bundle, saved draft, submitted job and public post are different outcomes. Act within the platform/account/scope already authorized by the user; do not repeatedly seek approval that was already given. If public publication has not been authorized, complete the reviewable content first and obtain that final authorization. Never infer that permission to prepare one platform grants permission to publish all variants. Verify a real remote ID/status/URL before claiming success; reconcile an uncertain submission before retrying.

Return the actual deliverables, the verified publication state and any material unfinished dependency. Keep logs, source evidence, licenses and receipts in the working project, out of public article copy and out of reusable skill releases.
