# Local expressive voice cloning

Use this route when a user wants narration in an authorized speaker's voice.
The executable adapter is **IndexTTS-2.5**, extracted from an actual long-form
production workflow. It synthesizes speech; `narrate` assembles audio and `mix`
combines it with the picture, original sound and music. Other voice engines can
still supply WAV files directly to `narrate`.

## Runtime and authorization

- Use the speaker/reference/use already authorized in the conversation. Record
  that authorization in the private plan; do not ask again just to populate it.
  A text statement is provenance, not an automated legal or identity check.
- Keep the original recording, excerpt, transcript, manifests, cloned output and
  licenses in the user's private project, **outside the public toolkit checkout**.
  The sample plan's authorization fields must be replaced with actual information.
- Install the engine separately from the official
  [IndexTTS repository](https://github.com/index-tts/index-tts), using its own
  environment and installation instructions. The adapter was integrated against
  revision `d9e41aac89fd00b3d71497fddb287b7f24613712` (`indextts.infer_v2_5.IndexTTS2`).
  Upstream changes may require an adapter update; this is not an adapter for 1.x/2.0.
- Obtain the [IndexTTS-2.5 weights](https://huggingface.co/IndexTeam/IndexTTS-2.5)
  and ancillary speech models separately under their own terms. Keep upstream
  code/model notices with production provenance. The toolkit's MIT license does
  not relicense them; no upstream inference code or weights are bundled.
- `clone --check` validates the local file layout listed in `voice_clone.py` and
  the reference duration, without constructing a model. It does **not** prove
  dependencies, accelerator availability or successful inference. Use an actual
  short sample to verify those. Pre-stage w2v-bert, BigVGAN and CAMPPlus too.
- Use `STORYTELLING_PYTHON=/path/to/index-tts/.venv/bin/python` for `clone`.
  This avoids forcing PyTorch/model dependencies on ordinary editing users. The
  tested production runtime used CPU float32 with acceleration disabled. CUDA
  can be selected explicitly but is not silently substituted or claimed tested.
- This adapter has no cloud upload or model-download command. It sets Hugging
  Face/Transformers offline flags, but runs locally installed third-party code;
  those flags are not an OS network sandbox. Use host network isolation if the
  production environment requires that guarantee.

## Sample, direct, regenerate

Copy [clone.json](../video/examples/clone.json) into the private project. All
paths inside it resolve relative to that JSON file, independently of shell cwd.
Choose a clean, contiguous voiced excerpt (often 6–15 seconds): one speaker, no
music or overlapping speech. `reference.in` / `out` are source-recording seconds.
The adapter makes a mono 24 kHz PCM reference with a mild 65 Hz high-pass and tiny
edge fades. It does not aggressively denoise or splice different deliveries.

```bash
# Run from this skill folder; replace paths with the authorized local setup.
STORYTELLING_PYTHON=/path/to/index-tts/.venv/bin/python python video/run clone /path/to/clone.json --check
STORYTELLING_PYTHON=/path/to/index-tts/.venv/bin/python python video/run clone /path/to/clone.json --out /path/to/work/voice-v1 --section opening
# Listen to segments/opening.wav, revise its script/direction if needed, then:
STORYTELLING_PYTHON=/path/to/index-tts/.venv/bin/python python video/run clone /path/to/clone.json --out /path/to/work/voice-v1 --resume
```

Each section has a unique ASCII `id`, spoken `text`, optional translated `en`,
`language` (`zhen`, `ja`, `es`, `ar`), `mood`, `seed`, `duration_factor` and an
optional `max_duration` guard (default 90 seconds). Use short spoken paragraphs,
not an entire essay as one inference. `en` is caption text, not a second dub.

Four mild **editorial presets** are provided: `curious`, `clear`, `engaged`,
`warm`. An explicit `emotion_vector` overrides the preset in this order:
`happy, angry, sad, afraid, disgusted, melancholic, surprised, calm` (eight finite
values, each 0–1). The upstream engine biases and normalizes their combined
intensity; the manifest records both requested and applied values. These are
artistic controls, not measured emotional scores or a guarantee of naturalness.
`duration_factor` is 0.5–2.0: below 1 generally shortens delivery; above 1 lengthens
it. Rewrite phrasing before resorting to extreme speed changes. Seeds aid reuse
but do not guarantee bit-identical inference across hardware/library versions.

`--section id` can be repeated. `--resume` reuses a section only when its input
signature **and output hash** match. Text, emotion/speed, reference bytes, model
weights, engine source, adapter code and selected package versions are included.
Hashing large weights costs time intentionally; no mtime-only model cache is used.
Keep runtime/model files unchanged during a run. Changing only the gap recalculates
the assembly clock without re-synthesizing audio. A changed unselected section
makes the run partial and removes the old assembly plan until it is regenerated.

Completed paragraphs survive a failed/interrupted run; `.partial.wav` files are
not promoted. A `.clone.lock` prevents concurrent writers. After a forced process
kill, verify the recorded PID is no longer running before deleting a stale lock.
There is no indefinite retry loop. Snapshot a finished output directory before
using `--resume` to revise it if the earlier edition must remain available.

## Verify actual speech, then assemble

The output is individual `segments/<id>.wav`, a private prepared reference and
`manifest.json`. A complete run also writes `narration-plan.json` with **measured
audio durations** and the requested gaps. It is a sequential draft clock: move
starts to the accepted edit timing before final assembly when needed. Default
captions span paragraphs; these are not fabricated word-level timestamps.

```bash
# Use your ASR environment for transcribe, not necessarily the TTS environment.
python video/run transcribe /path/to/work/voice-v1/segments/opening.wav --model /path/to/local-whisper --language zh --out /path/to/work/asr/opening.json
# Repeat transcribe for each generated paragraph, keeping <section-id>.json names.
python video/run voice-check /path/to/work/voice-v1/manifest.json --transcripts /path/to/work/asr --out /path/to/work/voice-review.json
python video/run narrate /path/to/work/voice-v1/narration-plan.json --out /path/to/work/assembled-v1
python video/run mix /path/to/mix.json --out /path/to/outputs/film-v1
```

`voice-check --section opening` also works on a sample. It requires ASR generated
from that exact audio hash; regenerate old transcripts lacking `source_sha256`.
Use new ASR/report paths after revising audio. It reports normalized character
error rate, wording differences, repetitions, clipping and phrase candidates
based on actual ASR word spans. Unmatched script text gets **no invented timing**.
Candidates can overlap if a recognized word spans a phrase boundary: review and
merge them before using them as caption cues. No report silently marks captions
as editorially approved or overwrites the speech manifest.

Exit codes: `voice-check` returns 0 for no automated flags, 2 for review flags,
1 for invalid/missing inputs. A low CER is **not** a speaker-similarity score,
pronunciation check or emotional-naturalness approval. ASR can mishear names and
numbers; listen before changing correct speech to fit the recognizer. Listen to
the final mix too: energetic music must not bury consonants or original speakers.
