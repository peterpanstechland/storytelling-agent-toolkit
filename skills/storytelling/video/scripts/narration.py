#!/usr/bin/env python3
"""Assemble externally generated narration and mix a finished video. No TTS downloads.

Usage: run narrate PLAN.json --out NEW_DIR
       run mix PLAN.json --out NEW_DIR
See references/video-production.md for the independent timeline contracts.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

from render import RenderError, decimal, ffmpeg_base, local_file, number, run, srt_time

RATE = 48000


def metadata(path, ffprobe):
    return json.loads(run([ffprobe, "-v", "error", "-show_streams", "-show_format",
                           "-of", "json", path]))


def stream(meta, kind):
    return next((s for s in meta.get("streams", []) if s.get("codec_type") == kind
                 and not s.get("disposition", {}).get("attached_pic")), None)


def duration(meta, kind, label):
    item = stream(meta, kind)
    if item is None:
        raise RenderError(f"{label} has no {kind} stream")
    return number(float(item.get("duration", meta.get("format", {}).get("duration", "nan"))),
                  f"{label} duration", minimum=1 / RATE)


def boolean(value, label):
    if type(value) is not bool:
        raise RenderError(f"{label} must be true or false")
    return value


def read_plan(path):
    def invalid_constant(value):
        raise RenderError(f"Invalid JSON number: {value}")
    plan = json.loads(path.read_text(encoding="utf-8-sig"), parse_constant=invalid_constant)
    if not isinstance(plan, dict) or type(plan.get("version")) is not int or plan["version"] != 1:
        raise RenderError("Plan must be an object with version: 1")
    return plan


def gain(value, label):
    return number(value, label, minimum=-96, maximum=24)


def samples(seconds):
    return math.floor(seconds * RATE + 0.5)


def limiter(ffmpeg, warnings, ceiling=0.84):
    help_text = run([ffmpeg, "-hide_banner", "-h", "filter=alimiter"])
    text = f"alimiter=limit={ceiling}:level=false"
    if re.search(r"^\s*latency\s+", help_text, re.MULTILINE):
        return text + ":latency=true"
    warnings.append("FFmpeg lacks limiter latency compensation; using 0.1 ms attack.")
    return text + ":attack=0.1"


def audio_peak(path, ffmpeg):
    result = subprocess.run([ffmpeg, "-hide_banner", "-nostdin", "-i", str(path),
                             "-vn", "-af", "volumedetect", "-f", "null", "-"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                            text=True, encoding="utf-8", errors="replace", check=False)
    if result.returncode:
        raise RenderError("Output audio level check failed: " + result.stderr[-1000:])
    match = re.search(r"max_volume:\s*(-?[\d.]+|inf|-inf) dB", result.stderr)
    value = float(match.group(1)) if match else None
    return value if value is not None and math.isfinite(value) else None


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def source_record(path, seconds):
    return {"source": str(path), "sha256": sha256(path), "source_duration": seconds}


def verify_audio(path, seconds, ffmpeg, ffprobe):
    measured = duration(metadata(path, ffprobe), "audio", str(path))
    if abs(measured - seconds) > 1 / RATE + 0.00001:
        raise RenderError(f"Audio duration mismatch: expected {seconds}, got {measured}")
    peak = audio_peak(path, ffmpeg)
    if peak is not None and peak > -0.5:
        raise RenderError(f"Output sample peak has insufficient headroom: {peak} dBFS")
    return {"duration": measured, "sample_peak_dbfs": peak,
            "sample_rate": RATE, "true_peak_measured": False,
            "listening_review": "required"}


def caption_text(item, field, label, default=""):
    value = item.get(field, default)
    if not isinstance(value, str) or "\x00" in value or "-->" in value:
        raise RenderError(f"{label}.{field} must be plain subtitle text")
    return value.strip()


def assemble(plan, base, tmp, ffmpeg, ffprobe):
    items = plan.get("segments")
    if not isinstance(items, list) or not items:
        raise RenderError("segments must be a nonempty array of generated/recorded audio files")
    allow_overlap = boolean(plan.get("allow_overlap", False), "allow_overlap")
    backend = plan.get("backend", {})
    if not isinstance(backend, dict):
        raise RenderError("backend must be a provenance object, not an executable command")
    warnings, segments, captions = [], [], []
    identifiers = set()
    for index, item in enumerate(items):
        label = f"segments[{index}]"
        if not isinstance(item, dict):
            raise RenderError(f"{label} must be an object")
        source = local_file(item.get("source"), base, label + ".source")
        source_seconds = duration(metadata(source, ffprobe), "audio", label)
        start = number(item.get("start"), label + ".start", minimum=0)
        trim_start = number(item.get("trim_start", 0), label + ".trim_start", minimum=0)
        trim_end = number(item.get("trim_end", source_seconds), label + ".trim_end", minimum=0)
        if trim_end <= trim_start or trim_end > source_seconds + 1 / RATE:
            raise RenderError(f"{label} trim must lie inside its audio file")
        ident = item.get("id", f"segment-{index + 1:04d}")
        if not isinstance(ident, str) or not ident or ident in identifiers:
            raise RenderError(f"{label}.id must be a unique nonempty string")
        identifiers.add(ident)
        start_samples = samples(start)
        length_samples = samples(trim_end - trim_start)
        if length_samples < 1:
            raise RenderError(f"{label} must retain at least one audio sample")
        actual_start, length = start_samples / RATE, length_samples / RATE
        entry = {"id": ident, **source_record(source, source_seconds),
                 "start": actual_start, "end": actual_start + length,
                 "start_samples": start_samples, "length_samples": length_samples,
                 "trim_start": trim_start, "trim_end": trim_end,
                 "gain_db": gain(item.get("gain_db", 0), label + ".gain_db")}
        segments.append(entry)
        phrase_list = item.get("captions")
        if phrase_list is None:
            phrase_list = [{"start": 0, "end": length,
                            "zh": caption_text(item, "text", label),
                            "en": caption_text(item, "en", label)}]
            timing = "measured_audio_segment"
        else:
            timing = item.get("caption_timing", "supplied_phrase_alignment")
            if not isinstance(phrase_list, list) or not isinstance(timing, str):
                raise RenderError(f"{label}.captions must be an array; caption_timing a string")
        last_end = 0
        for ci, cap in enumerate(phrase_list):
            if not isinstance(cap, dict):
                raise RenderError(f"{label}.captions[{ci}] must be an object")
            cs = number(cap.get("start"), label + ".caption.start", minimum=0)
            ce = number(cap.get("end"), label + ".caption.end", minimum=0)
            if ce <= cs or ce > length + 1 / RATE or cs < last_end - 1 / RATE:
                raise RenderError(f"{label} captions must be ordered, nonoverlapping, and inside retained audio")
            last_end = ce
            captions.append({"segment_id": ident, "start": actual_start + cs,
                             "end": actual_start + min(ce, length),
                             "zh": caption_text(cap, "zh", label),
                             "en": caption_text(cap, "en", label), "timing_method": timing})
    segments.sort(key=lambda item: item["start"])
    latest_end = 0
    for segment in segments:
        if segment["start"] < latest_end - 1 / RATE:
            if not allow_overlap:
                raise RenderError("Narration segments overlap; revise start times or explicitly set allow_overlap: true")
            warnings.append("Narration overlap explicitly enabled; listen for competing speech and stacked captions.")
        latest_end = max(latest_end, segment["end"])
    seconds = samples(number(plan.get("duration", latest_end), "duration", minimum=1 / RATE)) / RATE
    if seconds < latest_end - 1 / RATE:
        raise RenderError("duration would cut off narration; lengthen the video or revise narration")
    command = ffmpeg_base(ffmpeg)
    for segment in segments:
        command += ["-i", segment["source"]]
    graph = []
    for index, segment in enumerate(segments):
        graph.append(f"[{index}:a:0]atrim=start={decimal(segment['trim_start'])}:"
                     f"end={decimal(segment['trim_end'])},asetpts=PTS-STARTPTS,"
                     f"aresample={RATE},aformat=sample_fmts=fltp:channel_layouts=mono,"
                     f"apad,atrim=end_sample={segment['length_samples']},"
                     f"volume={decimal(segment['gain_db'])}dB,"
                     f"adelay={segment['start_samples']}S:all=1[s{index}]")
    inputs = "".join(f"[s{i}]" for i in range(len(segments)))
    graph.append(f"{inputs}amix=inputs={len(segments)}:duration=longest:dropout_transition=0:normalize=0,"
                 f"{limiter(ffmpeg, warnings, 0.89)},apad,atrim=end_sample={samples(seconds)}[a]")
    run(command + ["-filter_complex", ";".join(graph), "-map", "[a]", "-c:a", "pcm_s24le",
                   "-ar", str(RATE), "-ac", "1", tmp / "narration.wav"])
    captions.sort(key=lambda item: (item["start"], item["end"]))
    for language in ("zh", "en"):
        blocks = []
        for caption in captions:
            if caption[language]:
                blocks.append(f"{len(blocks)+1}\n{srt_time(caption['start'])} --> "
                              f"{srt_time(caption['end'])}\n{caption[language]}\n")
        (tmp / f"{language}.srt").write_text("\n".join(blocks), encoding="utf-8")
    return {"operation": "narrate", "duration": seconds, "backend": backend,
            "segments": segments, "captions": captions,
            "caption_clock": "finished_video_timeline_seconds",
            "audio": verify_audio(tmp / "narration.wav", seconds, ffmpeg, ffprobe),
            "warnings": warnings}, ["narration.wav", "zh.srt", "en.srt"]


def ducking(value, label):
    if not isinstance(value, dict):
        raise RenderError(f"{label} must be an object")
    enabled = boolean(value.get("enabled", True), label + ".enabled")
    threshold = number(value.get("threshold_db", -32), label + ".threshold_db", minimum=-60, maximum=-1)
    ratio = number(value.get("ratio", 8), label + ".ratio", minimum=1, maximum=20)
    attack = number(value.get("attack_ms", 15), label + ".attack_ms", minimum=0.01, maximum=2000)
    release = number(value.get("release_ms", 400), label + ".release_ms", minimum=0.01, maximum=9000)
    filt = (f"sidechaincompress=threshold={decimal(10 ** (threshold / 20))}:ratio={decimal(ratio)}:"
            f"attack={decimal(attack)}:release={decimal(release)}:makeup=1")
    return enabled, filt, {"enabled": enabled, "threshold_db": threshold, "ratio": ratio,
                           "attack_ms": attack, "release_ms": release}


def check_srt(path, seconds):
    text = path.read_text(encoding="utf-8-sig")
    matches = re.findall(r"(\d+):(\d\d):(\d\d),(\d{3}) --> (\d+):(\d\d):(\d\d),(\d{3})", text)
    if text.strip() and not matches:
        raise RenderError(f"No valid SRT timestamps in {path}")
    for match in matches:
        values = [int(value) for value in match]
        a = values[0] * 3600 + values[1] * 60 + values[2] + values[3] / 1000
        b = values[4] * 3600 + values[5] * 60 + values[6] + values[7] / 1000
        if b <= a or b > seconds + 0.001:
            raise RenderError(f"SRT cue outside the finished video timeline: {path}")
    return text, len(matches)


def mix(plan, base, tmp, ffmpeg, ffprobe):
    warnings = []
    video = local_file(plan.get("video"), base, "video")
    video_meta = metadata(video, ffprobe)
    seconds = duration(video_meta, "video", "video")
    vs = stream(video_meta, "video")
    if abs(float(vs.get("start_time", 0))) > 0.05:
        raise RenderError("mix expects a finished video with timestamps starting at zero; normalize the edit first")
    voice = plan.get("narration")
    if not isinstance(voice, dict):
        raise RenderError("narration must be an object with source and optional gain_db")
    voice_path = local_file(voice.get("source"), base, "narration.source")
    voice_seconds = duration(metadata(voice_path, ffprobe), "audio", "narration")
    if voice_seconds > seconds + 1 / RATE:
        raise RenderError("Narration extends past the video; do not silently cut off speech")
    voice_gain = gain(voice.get("gain_db", 0), "narration.gain_db")
    original = plan.get("original", {})
    if not isinstance(original, dict):
        raise RenderError("original must be an object")
    policy = original.get("policy", "preserve")
    if policy not in ("preserve", "mute"):
        raise RenderError("original.policy must be preserve or mute")
    original_gain = gain(original.get("gain_db", -9), "original.gain_db")
    music = plan.get("music")
    music_path = None
    music_spec = None
    if music is not None:
        if not isinstance(music, dict):
            raise RenderError("music must be an object")
        music_path = local_file(music.get("source"), base, "music.source")
        music_seconds = duration(metadata(music_path, ffprobe), "audio", "music")
        enabled, duck_filter, duck_spec = ducking(music.get("ducking", {}), "music.ducking")
        music_spec = {**source_record(music_path, music_seconds),
                      "gain_db": gain(music.get("gain_db", -20), "music.gain_db"),
                      "loop": boolean(music.get("loop", True), "music.loop"),
                      "fade_in": min(seconds, number(music.get("fade_in", 0.6), "music.fade_in", minimum=0)),
                      "fade_out": min(seconds, number(music.get("fade_out", 1.5), "music.fade_out", minimum=0)),
                      "ducking": duck_spec}
    command = ffmpeg_base(ffmpeg) + ["-i", video, "-i", voice_path]
    if music_path:
        if music_spec["loop"]:
            command += ["-stream_loop", "-1"]
        command += ["-i", music_path]
    norm = f"asetpts=PTS-STARTPTS,aresample={RATE},aformat=sample_fmts=fltp:channel_layouts=stereo"
    tail = f"apad,atrim=end_sample={samples(seconds)}"
    graph = [f"[1:a:0]{norm},volume={decimal(voice_gain)}dB,{tail},"
             f"{limiter(ffmpeg, warnings, 0.89)}[voice]"]
    mix_inputs = ["[voice]"]
    if stream(video_meta, "audio") and policy == "preserve":
        graph.append(f"[0:a:0]{norm},volume={decimal(original_gain)}dB,{tail}[original]")
        mix_inputs.append("[original]")
    elif policy == "preserve":
        warnings.append("The finished video has no original audio stream to preserve.")
    if music_spec:
        fades = ""
        if music_spec["fade_in"]:
            fades += f",afade=t=in:d={decimal(music_spec['fade_in'])}"
        if music_spec["fade_out"]:
            fades += f",afade=t=out:st={decimal(seconds-music_spec['fade_out'])}:d={decimal(music_spec['fade_out'])}"
        graph.append(f"[2:a:0]{norm},volume={decimal(music_spec['gain_db'])}dB,{tail}{fades}[music]")
        if music_spec["ducking"]["enabled"]:
            graph.append("[voice]asplit=2[voice_mix][voice_sidechain]")
            mix_inputs[0] = "[voice_mix]"
            graph.append(f"[music][voice_sidechain]{duck_filter}[ducked_music]")
            mix_inputs.append("[ducked_music]")
        else:
            mix_inputs.append("[music]")
    graph.append("".join(mix_inputs) + f"amix=inputs={len(mix_inputs)}:duration=longest:"
                 f"dropout_transition=0:normalize=0,{limiter(ffmpeg, warnings)},{tail}[a]")
    run(command + ["-filter_complex", ";".join(graph), "-map", "[a]", "-c:a", "pcm_s24le",
                   "-ar", str(RATE), "-ac", "2", tmp / "mixed.wav"])
    audio_metrics = verify_audio(tmp / "mixed.wav", samples(seconds) / RATE, ffmpeg, ffprobe)
    run(ffmpeg_base(ffmpeg) + ["-i", video, "-i", tmp / "mixed.wav", "-map", "0:v:0",
                               "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                               "-t", decimal(seconds), "-map_metadata", "-1", "-movflags", "+faststart",
                               tmp / "master.mp4"])
    output_meta = metadata(tmp / "master.mp4", ffprobe)
    if abs(duration(output_meta, "video", "master") - seconds) > 0.05 or not stream(output_meta, "audio"):
        raise RenderError("Muxed output duration or audio stream check failed")
    encoded_peak = audio_peak(tmp / "master.mp4", ffmpeg)
    if encoded_peak is not None and encoded_peak >= 0:
        raise RenderError("AAC output reaches clipping; reduce gains and rerender")
    subtitle_spec = plan.get("subtitles", {})
    if not isinstance(subtitle_spec, dict):
        raise RenderError("subtitles must map zh/en to SRT paths in finished video time")
    names = ["mixed.wav", "master.mp4"]
    subtitles = {}
    for language in ("zh", "en"):
        if language in subtitle_spec:
            path = local_file(subtitle_spec[language], base, f"subtitles.{language}")
            text, count = check_srt(path, seconds)
            (tmp / f"{language}.srt").write_text(text, encoding="utf-8")
            names.append(f"{language}.srt")
            subtitles[language] = {"source": str(path), "cue_count": count, "burned_in": False}
    return {"operation": "mix", "duration": seconds, "video": str(video),
            "narration": {**source_record(voice_path, voice_seconds), "gain_db": voice_gain},
            "original": {"policy": policy, "gain_db": original_gain}, "music": music_spec,
            "audio": audio_metrics, "encoded_sample_peak_dbfs": encoded_peak,
            "subtitles": subtitles, "warnings": warnings}, names


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("narrate", "mix"))
    parser.add_argument("plan", type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        raise RenderError("ffmpeg and ffprobe are required")
    plan_path = args.plan.expanduser().resolve(strict=True)
    plan = read_plan(plan_path)
    out = args.out.expanduser().absolute()
    if out.is_symlink() or (out.exists() and (not out.is_dir() or any(out.iterdir()))):
        raise RenderError("Output must be a new or empty nonsymlink directory")
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".storytelling-audio-", dir=out.parent) as work:
        tmp = Path(work)
        result, names = (assemble if args.command == "narrate" else mix)(
            plan, plan_path.parent, tmp, ffmpeg, ffprobe)
        result.update({"version": 1, "plan_path": str(plan_path),
                       "created_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
                       "ffmpeg_version": run([ffmpeg, "-version"]).splitlines()[0]})
        (tmp / "manifest.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (tmp / "plan.snapshot.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        names += ["manifest.json", "plan.snapshot.json"]
        if any(out.iterdir()):
            raise RenderError("Output became nonempty during rendering; refusing to overwrite")
        published = []
        try:
            for name in names:
                with (out / name).open("xb") as destination:
                    published.append(out / name)
                    with (tmp / name).open("rb") as source:
                        shutil.copyfileobj(source, destination)
        except BaseException:
            for path in published:
                path.unlink(missing_ok=True)
            raise
    print(f"{args.command} completed: {out}")


if __name__ == "__main__":
    try:
        main()
    except (RenderError, OSError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        sys.exit(130)
