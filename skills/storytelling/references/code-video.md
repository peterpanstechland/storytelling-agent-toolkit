# Code-native films, lyric timing and character performance

Use this route when the picture is built in code: a motion-graphics style, a karaoke line, a beat-locked character, or a title card that needs grain, bloom or a few particles. Footage editing stays in the [video guide](video-production.md). Shot grammar stays in [cinematic language](cinematic-language.md). Licences for the surveyed repositories are in [fx sources](fx-sources.md).

Pages still export through [web capture](web-capture.md). Implement `window.renderFrame(seconds)` and keep every frame a pure function of time.

## Pick a style, then adapt it

```bash
python codevideo/styles.py find 水墨
python codevideo/styles.py find bauhaus
python codevideo/styles.py list
```

Two MIT libraries are vendored as text, without their films, fonts, models or audio:

- Lemo-Opuscar, 51 style briefs: [styles/lemo/README.md](../codevideo/styles/lemo/README.md). Read that style's `STYLE.md` (grid, palette, motion, type, sound). The brief was written for the upstream renderer. Rebuild the look with this toolkit's page contract. Do not clone the upstream repo into a skill release, and do not copy a historical poster, a trademark or a font file the brief tells you to avoid.
- Fifteen motion-graphics prompts: [styles/mg/INDEX.md](../codevideo/styles/mg/INDEX.md). Keep the signature features, replace the creative seed with the story you were asked to tell, and review against [rubric.md](../codevideo/styles/mg/rubric.md). [template.md](../codevideo/styles/mg/template.md) is the blank for a new style. Demo films stay upstream; the prompt links point at them.

A style name is a treatment, not a finished film. Render a still, then a short low-resolution movie, and look at both.

## Lyric and karaoke timing

```bash
python codevideo/karaoke.py codevideo/examples/lyrics.json --output /tmp/lyrics-v1 --samples 8
```

`examples/lyrics.json` is original demo copy, not a song you can publish as someone else's lyric. Supply your own word timings. The tool writes `lyrics.ass` (libass `\k` wipes) and `cues.json`. It does not download audio. Word progress, including syllable wipes, comes from the MIT timing model in mexicat/pdoom-video; the song and scenes from that repository are not included. Burn the ASS with FFmpeg in the video workflow, then watch the wipe against the voice.

## Character performance

[templates/character-beat.html](../templates/character-beat.html) is a 1280×720 page: one figure walks through emotion keys, another dances on the beat. Pose math for the 31 emotions and the dances is ported from ClaudeAnimationBase (MIT). The drawn figure is a geometric stand-in, not the upstream painted character, and the p5 brush renderer is not included.

```bash
node scripts/capture_web.mjs \
  --input templates/character-beat.html \
  --output /tmp/character-v1 --mode video \
  --width 1280 --height 720 --seconds 8 --fps 24
```

Edit `KEYS` and `DANCES` in the page. Keep frames pure. `onTwos` holds each drawing for two frames at 24 fps. Change the silhouette when the story needs a different character; do not trace the upstream model sheet.

## Title-card grain, bloom, vignette, particles

```bash
python codevideo/looks.py cards/cover.png --output /tmp/cover-graded.png --look grain,bloom,vignette,particles --time 0.4
```

`codevideo/looks.py` is original Pillow code. three.quarks and react-postprocessing were not copied. Use a light grain on a title card; do not grade a shot that is supposed to stay a faithful record of an event.

## Finding other code-rendered videos

```bash
python codevideo/catalog.py
python codevideo/catalog.py --category explainer --tag canvas --limit 8
```

The index lists 703 public posts from awesome-opus5-5-videos (MIT compilation): category, tags, author, post URL and a link to the upstream prompt file. Prompt text is not stored. Read it upstream and keep the original author's credit. Unlicensed prompt collections are linked from [fx sources](fx-sources.md) and must not be copied in.
