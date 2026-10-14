# Video production: evidence, clocks, voice and delivery

Use this reference for real-footage edits, narrated explainers and revisions. For
camera, title, VFX and grade decisions, read [cinematic language](cinematic-language.md).
The bundled tools execute plans; the agent supplies story decisions, visual
interpretation, factual checks and translation. Deliver an actual rendered file
when the user requests an edit.

## Runtime and commands

From the installed skill folder (or substitute an absolute path to `video/run`):

```sh
python3 video/run doctor
python3 video/run inspect ./media --out ./work/index-v001
python3 video/run transcribe ./media/interview.mp4 --model ./models/asr --out ./work/transcript.json --language zh
python3 video/run render ./work/edit-v001.json --out ./outputs/visual-v001 --preview
python3 video/run narrate ./work/narration-v001.json --out ./outputs/voice-v001
python3 video/run mix ./work/mix-v001.json --out ./outputs/mixed-v001
```

- Python 3.10+ and FFmpeg/FFprobe on `PATH` are the base. `render`, `narrate` and
  `mix` use the standard library. H.264 export requires libx264; subtitles require
  libass and fonts with the requested language's glyphs. Contact sheets use Pillow.
- Install optional inspection/ASR packages in your own environment from
  `video/requirements-inspect.txt` or `video/requirements-asr.txt`. Requirements
  are compatible ranges, not a reproducibility lock; record actual versions.
- The launcher uses the invoking Python. `STORYTELLING_PYTHON` may point to a
  different executable; its value is a path, not a command with shell arguments.
  On Windows use `python path/to/video/run`, with FFmpeg on `PATH`.
- `doctor --require audio` checks mixing; `doctor --require transcribe --model
  ./models/asr` checks an existing ASR directory. Missing optional ASR does not
  prevent editing. No model, voice sample, music, media, virtualenv or credentials
  ship in this repository.
- Transcription is local-only unless the caller explicitly passes `--download`.
  That flag permits an ASR model download; it does not upload the source audio.
  A local model should be selected and licensed by the user/project.
- Examples under `video/examples/` contain placeholder paths and are contracts,
  not runnable demonstrations without the user's media.

## Inspect before choosing shots

Index sources, open contact sheets, then inspect candidate moments densely and
in motion. A sparse sheet does not establish that an entire video was watched.
Record source file, in/out, observed action, audible speech, actual speaker,
story role and relevant brand/rights restrictions in a project-local shot log.
Keep originals unchanged and make proxies/outputs in separate directories.

Use word timestamps around speech cuts; verify names, numbers and technical
terms. A machine transcript is a draft. When ASR cannot run, use a supplied
transcript with checked timing or report the gap, without inventing dialogue.
Inspect metadata and real frames before grading; this renderer rejects PQ/HLG
input. A 10-bit stream alone does not establish HDR, and missing Log metadata
does not establish a calibrated camera transform.

### Identity and attribution

First-person narration over another presenter's image can falsely imply that
they are the author. Before “I built” or “our project,” show the verified author,
actual project interface, or clearly relevant activity. An unrelated presenter
may be a brief event cutaway with a neutral context label; do not reuse their
image as the narrator's identity. Screen images of celebrities and projected
slides count as visible content when the user excludes celebrity appearances.

Keep personal byline, partner branding, project name and product name distinct.
Use approved logo artwork. Record the current brief's treatment of prominent
versus incidental marks; a user's decision to leave tiny blurred marks in one
film is not a global rule. Do not reproduce customer/private source assets in a
public toolkit. Licensing and attribution belong in the production record and
appropriate credits, not an intrusive internal-workflow paragraph on every shot.

## Edit contract: source clock

`render` reads a version-1 JSON plan. Every media path is local, absolute or
relative to the **plan's directory**, independent of the process working directory.

```json
{
  "version": 1,
  "title": "An experiment explained",
  "output": {"width": 1920, "height": 1080, "fps": 30, "fit": "contain"},
  "clips": [{"source": "../media/demo.mp4", "in": 4.0, "out": 10.0,
             "reason": "The observable result introduces the question"}],
  "captions": [{"clip": 0, "start": 5.0, "end": 8.0,
                "zh": "经过核对的实际台词", "en": "Verified spoken words"}]
}
```

- Clip in/out and captions start/end are **original source seconds**. Captions
  must fit their selected clip. Caption `clip` is the zero-based clip index.
- Final caption time = sum of preceding selected clip durations + source cue
  time − this clip's in-point. Update clip indices after reordering.
- Dimensions must be even. `contain` retains the complete frame with padding;
  `cover` center-crops, so verify faces, actions, screens and logos.
- Cuts are rounded at cumulative frame boundaries; the resulting deviation is
  less than a frame. No speed changes, animated crops or transitions are built
  into this schema. Export effects as inspected clips and cut those in.
- Captions represent actual speech. A visible editorial annotation should be
  distinguished, e.g. `【编辑注】` / `[Editor's note]`. Generated test footage must
  be labeled as test footage. Never assign invented dialogue to an actual person.
- `zh` and `en` are two supported language slots; no translation is generated.
  Empty language output is reported. Other subtitle languages require an
  adapted compositor rather than silently mislabeling output files.
- Optional music uses `{"source":"../media/music.wav","volume":0.12,
  "original_volume":1,"fade_in":0.3,"fade_out":1.5}`. These are linear gains,
  not LUFS targets. For narration, render without this music and use `mix`.

Outputs are `master.mp4`, burned-in `zh.mp4` / `en.mp4`, separate SRTs, a plan
snapshot and a manifest. Preview is a faster/smaller export; render the final
without `--preview`. Outputs require a new or empty directory and never replace
an existing version. Public sharing should omit manifests that expose private
file paths or source names.

## Voice generation: replaceable provider

The bundled `narrate` command **assembles existing audio; it does not synthesize
or clone speech**. Use a user-selected local engine or authorized service, then
pass its resulting files to the assembler. Check the provider's actual current
API, model license, hardware, supported language, expression controls and use
terms. This toolkit bundles no provider SDK, cloned voice, reference audio or
model weights. It can ingest recordings from a human narrator in exactly the
same way.

When cloning is requested, record who authorized it and the intended speaker.
Keep the reference and its exact transcript in the private project. Use an
available authorized voice; do not silently substitute a different person's
voice. Remote voice processing requires authorization for that destination;
local processing is not authorization to upload the sample.

Generate a short sample before the whole script. Listen for identity,
pronunciation, rhythm and expression. Rewrite long written sentences as spoken
phrases with intentional pauses and emphasis. Direct individual phrases (curious,
reflective, excited, calm); do not assume a speed slider establishes emotional
control. Preserve a speaker's quoted original audio when the film calls for it.
Clean noise conservatively and retain intelligibility; a dense denoiser is not a
substitute for the right excerpt.

Record engine/model revision, reference hash, reference transcript, per-phrase
text, delivery direction, supported generation settings, output hash and review
status. Never store tokens or reference recordings in the public repository.
Regenerate poor phrases rather than aggressively time-stretching them. If the
voice changes, regenerate alignment before shifting graphics or captions.

## Narration contract: finished-video clock

`narrate` accepts `version:1`, optional `duration`, a provenance `backend` object,
and `segments`. Backend metadata is data, never executable shell commands.

```json
{
  "version": 1,
  "duration": 12,
  "backend": {"engine": "chosen-provider", "provenance_file": "voice-provenance.json"},
  "segments": [{
    "id": "opening", "source": "../voice/001.wav", "start": 1.2,
    "trim_start": 0.1, "trim_end": 3.1, "gain_db": 0,
    "captions": [{"start": 0.2, "end": 2.6,
                  "zh": "已核对的旁白", "en": "Verified narration"}],
    "caption_timing": "reviewed_phrase_alignment"
  }]
}
```

- Segment `start` is **finished-video seconds**, rounded to a 48 kHz sample.
  Trim start/end are source-audio seconds; default retains the whole file.
- Caption offsets are relative to the **retained audio after trimming**, not
  the original source. Final cue = segment start + caption offset.
- Without `captions`, `text` / `en` receive the full measured phrase duration.
  These spans are not word alignment or proof that TTS spoke the intended words.
- Supplied cues must be ordered, nonoverlapping and contained in the retained
  phrase. Audio overlap is rejected unless `allow_overlap:true` is deliberate.
- Too-short `duration` is rejected; narration cannot silently be cut off. Gain
  accepts −96 to +24 dB. There is no automatic speech-speed or silence edit.
- ASR of an individual generated phrase has phrase-relative time; ASR of the
  full assembled track already has final-video time. Do not add offsets twice.

Outputs: mono 48 kHz/24-bit `narration.wav`, final-clock SRTs, snapshot and
manifest with hashes and measured durations. No English dub is generated.

## Mix contract

Use `video/examples/mix.json` as a starting point. The video should be a
zero-origin music-free visual master. `narration.source` is an assembled track
with its silent gaps intact. A short track is padded; a track longer than the
video is rejected. Video is stream-copied through the mixer.

`original.policy` is `preserve` (default gain −9 dB) or `mute`. Preserve valuable
real room/tool sound; source audio is not automatically ducked. Plan breaks or
lower its gain if original speakers compete with narration. `music` is optional,
may loop or silence-pad, and supports fades plus `sidechaincompress` ducking
driven by the actual narration signal, including pauses. Do not add the same
music both in `render` and again in `mix`.

Outputs: stereo 48 kHz/24-bit `mixed.wav`, AAC `master.mp4`, optional copied
SRTs, snapshot and manifest. **This mixer does not burn subtitles in.** Burn
final-clock subtitles over the mixed video with a separately checked command
or deliver them as external/selectable subtitles. Do not feed final-clock
narration SRTs into the source-clock edit-caption fields.

The commands check decoded sample peaks and duration, not integrated loudness
or true peaks. A limiter provides headroom and disables automatic gain boost.
When a delivery target requires loudness measurement, run a separate measured
pass and verify the encoded output. Mono-to-stereo conversion changes loudness
depending on the pan law; do not assume copying a sample into two channels
preserves LUFS.

## Review, revisions and release

Check opening, cuts, original-speech boundaries, peak effects, titles, subtitle
baselines, final frame, mobile crop and encoded stream properties. Listen to
voice over music and transitions. ASR/FFmpeg success is not a perceptual review;
state which checks were actually performed if playback is unavailable.

For a small correction, change only the authorized interval. Retain the previous
version, source evidence and transcript cache. When only picture changes, retain
the original audio stream when feasible and verify its hash/duration. An inserted
opening must shift all later visuals, speech, subtitles and effects from one
shared insertion event. Never maintain separate undocumented offsets.

Use one project-local final timeline as the source of truth. Deliver actual
MP4s, meaningful cover frame, requested subtitles and publication copy. The
platform publishing workflow is separate; rendering is not evidence of upload,
draft creation or publication.
