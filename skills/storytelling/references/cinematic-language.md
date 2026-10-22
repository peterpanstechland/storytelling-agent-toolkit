# Cinematic language for useful storytelling

Use these recipes to choose a visual treatment with a reason. They are
production guidance, **not built-in named effects in `video/run render`**. Specify
what the viewer should understand, then the shot, technique and available tool.
Export an actual preview before promising the effect. For a film authored in
code, start from [code video](code-video.md) instead of inventing a style name.

## Shot and rhythm grammar

- **Whip pan:** carry direction and blur across the edit to move between related
  spaces. Inspect the last/first clear frames; arbitrary horizontal blur does
  not make two opposing movements coherent.
- **Smash cut:** use a decisive change of scale, sound or consequence to reveal
  something. The destination must be legible; reserve the strongest cut.
- **Crash zoom:** push rapidly toward the meaningful control, result or reaction,
  then hold. Start with enough source resolution and keep the subject in frame.
- **Rhythmic montage:** find actual action onsets and musical accents. Vary shot
  lengths and include a longer landing shot. Do not attach a whoosh to every cut.
- **Visual comedy:** let setup and revealed consequence create the joke. Avoid
  fabricating failed experiments, misleading reactions or dialogue.
- **Symmetry and lateral moves:** align actual architecture or product parts to
  make structure readable; use a centered hold after a fast sequence.
- **Step printing / slow-shutter feeling:** repeat selected frames or composite
  controlled trails to express time and emotion. Keep critical demonstrations
  and measurements observable. It does not create extra temporal observations.
- **Bullet time / virtual camera:** use an adequate multi-view reconstruction or
  authored scene for a motivated new angle. Match action phase on entry/exit;
  do not claim a factual orbit from a single flat still.

The user's director references can guide different dimensions: Edgar Wright for
action/sound rhythm, Wes Anderson for composition, Wong Kar-wai for subjective
time/light, and the Wachowskis for spatial/time manipulation. Translate the
requested dimension into an original scene; a name is not a complete recipe.

## Opening sequence library

Select one family for the story and platform. These options are templates, not
obligatory branding. A short cold open followed by a compact identity often gives
short-form viewers useful information earlier than a long fixed ident.

1. **Studio ident:** a distinctive shape or material reveals the approved mark,
   holds, then hands its motion into the first shot.
2. **Epic opening:** build scale through a real establishing detail, restrained
   camera reveal and a strong musical landing. Do not invent attendance or stakes.
3. **Sci-fi opening:** turn a real signal, machine state or calculation into a
   legible visual path; reveal the subject before showing decorative interfaces.
4. **Cyberpunk opening:** connect physical texture and an electronic accent with
   restrained neon/contrast. Preserve skin, detail and readable product screens.
5. **Documentary opening:** an observed moment or real quotation poses a question;
   titles arrive after the audience knows what the story concerns.
6. **Action cold open:** begin at a clear action peak, pause on the unanswered
   question, then move into context. Do not spoil or exaggerate the outcome.
7. **Kinetic typography:** one or two meaningful words move with a spoken or
   musical beat, then settle into the identity. Avoid rapid paragraph reading.
8. **Experimental opening:** use a consistent material, collage or type rule.
   Return the viewer to a recognizable source anchor; avoid uncontrolled flashing.

A reusable **3-second** identity at 30 fps can use frames 0–17 for a source-shape
pickup, 18–41 for a short reveal, 42–74 for a clear identity hold, and 75–89 for
handoff. This is a starting rhythm, not an inescapable preset. A **12-second**
version can expand invitation → discovery → connection → breath → identity →
handoff, only where the content and platform warrant that time.

Trailer rhythm can compress hook → clue → question → pressure → breath → reveal
into a few purposeful shots. Design a sound map before rendering: a few accents,
one restrained riser, and a release. The strongest sound needs a destination.
The film's promise must be fulfilled by the actual story.

## VFX techniques and suitable implementation routes

All named libraries are optional candidates. Check installed versions and the
official APIs/licenses for the current task; do not install an entire stack
because it appears in this list.

- **Remotion + FFmpeg:** reusable React compositions; conforming, encoding,
  captioning, audio and platform variants. Check current Remotion license terms.
- **Motion Canvas + SVG:** mechanism diagrams, path drawing, sequential causality
  and data flow. Export a guided version of the explanation.
- **Three.js + GSAP or p5.js/Canvas/GLSL:** shader overlays, controlled particles,
  web scenes and deterministic animation. Render frame time, not wall-clock time.
- **Blender + Python:** modeled parts, physical geometry, camera/light animation,
  3D product reveals and offline compositing. Inspect occlusion along the path.
- **OpenCV + detection/tracking models:** geometry, optical flow and tracked
  anchors. Detection boxes are not verified identities or complete tracks.
- **SAM-style segmentation:** foreground masks and rotoscoping assistance. Check
  hair, hands, thin parts, fast actions, occlusion and shot boundaries.
- **Monocular depth models:** relative depth for masks or modest parallax. Their
  output is not calibrated metric distance or unseen back-surface geometry.
- **Interpolation models:** predict intermediate frames for retiming. Check
  crossing limbs, fast balls, nets and disocclusions; generated frames add no
  measured observations. Keep and remap the original time relationship.
- **ComfyUI or authorized generation services:** explicitly illustrative inserts,
  concept shots and stylization. Record provenance and inspect anatomy, logos,
  identity and physical continuity. Do not invent real product behavior.
- **DaVinci Resolve + Fusion:** detailed masks, grade, sound and finishing when
  available. Do not make completion depend on an absent paid feature.

### Choose the effect that explains the shot

Use keyframes to reveal **cause before effect**. A tracked label should follow
its observed anchor, while a title belongs to a deliberate composition. A
planar homography can map court/floor coordinates; it cannot recover arbitrary
3D geometry. Save calibration and inspect tracking after occlusion and cuts.

Use particles for a defined flow, accumulation or region. If color/density is
data-driven, document its variable, units, observation period and normalization.
If decorative, avoid a numeric legend implying measurement. Electric trails,
energy transfers and bloom need correct anchors, masks and a visible action.
A shader cannot supply missing statistics or prove a product capability.

Use a spatial replay only where an alternate view explains a relationship.
One motivated orbit followed by the matching real action is stronger than
repeating the same transition at every chapter. Call manual geometry an
**illustrative reconstruction**. Do not relabel soft particles, point-cloud
filters or depth-card parallax as trained 3D/4D Gaussian Splatting. Actual GS
needs an appropriate capture/reconstruction pipeline and validated geometry.

## Shared shot contract

Keep this production metadata outside the simple edit schema:

- shot ID, story question and observed claim;
- source file, source in/out/fps, final in/out/fps;
- source/final pixel spaces, crop/scale and anchor mapping;
- confirmed subject/speaker identity and relevant permissions;
- data reference, definition, unit, period and whether measured or illustrative;
- camera path, keyframes, masks, depth and occlusion dependencies;
- actual renderer/version, seed, assets and deterministic time parameter;
- narration phrase/caption cue, musical beat and sound onset;
- export duration/alpha/color format plus visual/audio review status.

At export, `time = frame_number / fps`. Remap source anchors after speed changes.
Use the same final clock for audio, captions and VFX. Keep clean plates and
separate text/data layers so corrections need not rebuild the entire scene.

## Color and reusable LUTs

Inspect transfer function, primaries, full/limited range, exposure, white balance
and camera differences. Apply an appropriate input transform for confirmed
Log/HDR before creative grading. A generic LUT is not a camera calibration.
Match neighboring shots first; preserve skin, whites, product colors and detail.

Apply creative grade to footage, then composite color-sensitive logos, UI and
text. Avoid grading overlays twice. A neon/cool-shadow look should retain
highlight headroom, black detail and legible screens. Review before/after frames
and the encoded output, including skin and gradients.

When requested, deliver an actual `.cube` with its intended input/output color
space, cube size, look and strength. Validate entry count, finite values, channel
ordering and black/white/neutral behavior. State whether it is a creative SDR
look rather than a calibrated transform. Verify it in the intended editor;
different color management can change its appearance. No LUT generator is
bundled in the basic CLI; use a verified compositor/editor implementation.

## Narration-led typography and data

Put the full explanation in narration/accurate captions. Show one brief question,
term or meaningful number at a time. Bind entrance/hold/exit to **measured**
speech or actual music beats. Allow a stable reading hold; avoid pulsing all
elements and covering the primary action.

Numbers retain definitions: a percentage needs its denominator/population,
conditions and observation period. A season-level index must not become a
frame-level probability by rescaling it. A dot grid illustrates a proportion;
it does not imply 100 observed attempts or future outcomes. Rephrase for a
first-time viewer and keep internal editing notes out of public-facing prose.

Check mobile readability, caption collisions, word timing, brand/byline
separation, peak-effect frames, source visibility and motion continuity. A still
style frame cannot establish pacing; a successful render cannot establish story
fidelity. Export, inspect, listen, and revise the smallest needed passage.

The `video/run autocut` tools implement several of these moves (whip, push, speed ramp, freeze/annotation, glitch, 360 reframing) with style presets: [auto edit: moves and effects](auto-edit-effects.md). Presets are starting points; judge each result on screen.

For a region/time-limited SDR brightness pass that preserves audio and frame timing, see [video revisions](video-revisions.md) and `video/run grade`. It does not generate or apply a camera-specific LUT.
