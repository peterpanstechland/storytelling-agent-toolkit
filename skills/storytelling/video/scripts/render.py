#!/usr/bin/env python3
"""Render a version-1 storytelling edit plan using Python's standard library and FFmpeg.

Usage: python render.py PLAN.json --out NEW_OR_EMPTY_DIRECTORY [--preview]
No models, packages, fonts, or media are downloaded by this program.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unicodedata


class RenderError(Exception):
    pass


def run(command, *, cwd=None):
    """Arguments are always passed directly; no shell is involved."""
    try:
        result = subprocess.run(
            [str(arg) for arg in command], cwd=cwd, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            encoding="utf-8", errors="replace", check=False,
        )
    except OSError as exc:
        raise RenderError(f"Cannot run {command[0]}: {exc}") from exc
    if result.returncode:
        raise RenderError(
            f"{Path(str(command[0])).name} failed ({result.returncode}):\n"
            + result.stderr[-6000:]
        )
    return result.stdout


def number(value, label, *, minimum=None, maximum=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RenderError(f"{label} must be a finite number")
    try:
        result = float(value)
    except (ValueError, OverflowError):
        raise RenderError(f"{label} must be a finite number") from None
    if not math.isfinite(result):
        raise RenderError(f"{label} must be a finite number")
    if minimum is not None and result < minimum:
        raise RenderError(f"{label} must be >= {minimum}")
    if maximum is not None and result > maximum:
        raise RenderError(f"{label} must be <= {maximum}")
    return result


def decimal(value):
    return f"{value:.9f}".rstrip("0").rstrip(".") or "0"


def local_file(value, base, label):
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise RenderError(f"{label} must name a local file")
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = base / path
    try:
        path = path.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise RenderError(f"{label}: {exc}") from exc
    if not path.is_file():
        raise RenderError(f"{label} is not a regular file: {path}")
    return path


def positive_duration(value):
    try:
        result = float(value)
        return result if math.isfinite(result) and result > 0 else None
    except (TypeError, ValueError, OverflowError):
        return None


def probe(path, ffprobe, cache):
    key = str(path)
    if key not in cache:
        result = run([
            ffprobe, "-v", "error", "-print_format", "json", "-show_entries",
            "format=duration:stream=index,codec_type,width,height,duration,"
            "sample_rate,channels,color_transfer,color_primaries,pix_fmt:"
            "stream_disposition=attached_pic", str(path),
        ])
        try:
            cache[key] = json.loads(result)
        except json.JSONDecodeError as exc:
            raise RenderError(f"ffprobe returned invalid metadata for {path}") from exc
    return cache[key]


def first_stream(metadata, kind):
    for stream in metadata.get("streams", []):
        if stream.get("codec_type") == kind:
            if kind == "video" and stream.get("disposition", {}).get("attached_pic"):
                continue
            return stream
    return None


def media_duration(metadata, stream):
    return positive_duration(stream.get("duration")) or positive_duration(
        metadata.get("format", {}).get("duration")
    )


def frame_boundary(seconds, fps):
    # Half-up rounding of cumulative time avoids a growing rounding error per cut.
    return math.floor(seconds * fps + 0.5)


def validate(plan, base, ffprobe, preview):
    if not isinstance(plan, dict) or type(plan.get("version")) is not int or plan["version"] != 1:
        raise RenderError("The plan must be an object with version: 1")
    if not isinstance(plan.get("title"), str) or not plan["title"].strip():
        raise RenderError("title must be a nonempty string")
    output = plan.get("output")
    if not isinstance(output, dict):
        raise RenderError("output must be an object")
    dimensions = []
    for key in ("width", "height"):
        value = output.get(key)
        if type(value) is not int or value < 2 or value > 7680 or value % 2:
            raise RenderError(f"output.{key} must be an even integer between 2 and 7680")
        dimensions.append(value)
    width, height = dimensions
    fps = number(output.get("fps"), "output.fps", minimum=1, maximum=120)
    fit = output.get("fit")
    if fit not in ("contain", "cover"):
        raise RenderError("output.fit must be contain or cover")
    if preview and height > 640:
        width = max(2, round(width * 640 / height / 2) * 2)
        height = 640
    source_clips = plan.get("clips")
    if not isinstance(source_clips, list) or not source_clips:
        raise RenderError("clips must be a nonempty array")
    cache, clips, warnings = {}, [], []
    elapsed = 0.0
    for index, item in enumerate(source_clips):
        label = f"clips[{index}]"
        if not isinstance(item, dict):
            raise RenderError(f"{label} must be an object")
        source = local_file(item.get("source"), base, f"{label}.source")
        metadata = probe(source, ffprobe, cache)
        video = first_stream(metadata, "video")
        if not video or not video.get("width") or not video.get("height"):
            raise RenderError(f"{label}: source has no usable video stream")
        if video.get("color_transfer", "").lower() in ("smpte2084", "arib-std-b67"):
            raise RenderError(
                f"{label}: HDR/PQ/HLG input is not supported in this renderer. "
                "Convert this source to SDR with a proper tone-mapping workflow first: "
                f"{source}"
            )
        duration = media_duration(metadata, video)
        if duration is None:
            raise RenderError(f"{label}: cannot determine source video duration")
        start = number(item.get("in"), f"{label}.in", minimum=0)
        end = number(item.get("out"), f"{label}.out", minimum=0)
        if end <= start:
            raise RenderError(f"{label}.out must be greater than in")
        if end > duration + 0.000001:
            raise RenderError(f"{label}.out ({end}) exceeds source duration ({duration})")
        audio = first_stream(metadata, "audio")
        start_frame = frame_boundary(elapsed, fps)
        end_frame = frame_boundary(elapsed + end - start, fps)
        if end_frame <= start_frame:
            raise RenderError(f"{label} is too short to produce a frame at {fps} fps")
        clips.append({
            "source": str(source), "in": start, "out": end,
            "reason": item.get("reason", ""), "source_duration": duration,
            "video_stream": video["index"],
            "audio_stream": audio["index"] if audio else None,
            "timeline_start": elapsed, "timeline_end": elapsed + end - start,
            "render_start": start_frame / fps, "render_end": end_frame / fps,
            "frames": end_frame - start_frame,
        })
        if not audio:
            warnings.append(f"Clip {index} has no audio; silence was added.")
        elapsed += end - start
    caption_items = plan.get("captions", [])
    if not isinstance(caption_items, list):
        raise RenderError("captions must be an array")
    captions = []
    for index, item in enumerate(caption_items):
        label = f"captions[{index}]"
        if not isinstance(item, dict):
            raise RenderError(f"{label} must be an object")
        clip_index = item.get("clip")
        if type(clip_index) is not int or not 0 <= clip_index < len(clips):
            raise RenderError(f"{label}.clip must be a valid zero-based clip index")
        clip = clips[clip_index]
        start = number(item.get("start"), f"{label}.start", minimum=0)
        end = number(item.get("end"), f"{label}.end", minimum=0)
        if start < clip["in"] or end > clip["out"] or end <= start:
            raise RenderError(f"{label} must lie entirely inside its source clip in/out")
        texts = {}
        for lang in ("zh", "en"):
            value = item.get(lang, "")
            if not isinstance(value, str) or "\x00" in value:
                raise RenderError(f"{label}.{lang} must be a string without NUL bytes")
            texts[lang] = " ".join(value.split())
        if not texts["zh"] and not texts["en"]:
            raise RenderError(f"{label} must contain at least one nonempty language")
        for lang in ("zh", "en"):
            if not texts[lang]:
                warnings.append(f"Caption {index} has no {lang} text.")
        mapped_start = clip["timeline_start"] + start - clip["in"]
        mapped_end = clip["timeline_start"] + end - clip["in"]
        # Preserve the requested time mapping; only trim any last-frame overshoot.
        mapped_end = min(mapped_end, clips[-1]["render_end"])
        if round(mapped_end * 1000) <= round(mapped_start * 1000):
            raise RenderError(f"{label} is too short after millisecond/frame quantization")
        captions.append({"clip": clip_index, "source_start": start, "source_end": end,
                         "start": mapped_start, "end": mapped_end, **texts})
    captions.sort(key=lambda item: (item["start"], item["end"]))
    for lang in ("zh", "en"):
        previous_end = -1.0
        for caption in captions:
            if caption[lang]:
                if caption["start"] < previous_end:
                    warnings.append(f"Overlapping {lang} captions may stack on screen.")
                    break
                previous_end = caption["end"]
    music = plan.get("music")
    if music is not None:
        if not isinstance(music, dict):
            raise RenderError("music must be an object")
        source = local_file(music.get("source"), base, "music.source")
        metadata = probe(source, ffprobe, cache)
        audio = first_stream(metadata, "audio")
        if not audio or media_duration(metadata, audio) is None:
            raise RenderError("music.source must contain finite-duration audio")
        music = {"source": str(source), "volume": number(
            music.get("volume", 0.12), "music.volume", minimum=0, maximum=2),
            "original_volume": number(music.get("original_volume", 1), "music.original_volume", minimum=0, maximum=2),
            "fade_in": number(music.get("fade_in", 0), "music.fade_in", minimum=0, maximum=30),
            "fade_out": number(music.get("fade_out", 0), "music.fade_out", minimum=0, maximum=30),
            "audio_stream": audio["index"]}
    if abs(clips[-1]["render_end"] - elapsed) > 0.000001 or any(
        abs(c["render_start"] - c["timeline_start"]) > 0.000001 for c in clips
    ):
        warnings.append("Cuts were rounded at cumulative frame boundaries; caption times "
                        "use planned clip-duration prefixes. Error stays below one frame.")
    return {"width": width, "height": height, "fps": fps, "fit": fit,
            "clips": clips, "captions": captions, "music": music,
            "planned_duration": elapsed, "render_duration": clips[-1]["render_end"],
            "warnings": warnings}


def srt_time(seconds):
    milliseconds = max(0, round(seconds * 1000))
    hours, milliseconds = divmod(milliseconds, 3600000)
    minutes, milliseconds = divmod(milliseconds, 60000)
    seconds, milliseconds = divmod(milliseconds, 1000)
    return f"{hours:02}:{minutes:02}:{seconds:02},{milliseconds:03}"


def wrap_caption(text, lang, width, height):
    # ASS subtitle rendering uses a height-relative font size. Wide text occupies
    # two character cells; English wraps at word boundaries where possible.
    font_pixels = max(12, height * 0.036)
    cells = max(12, int(width * 0.86 / (font_pixels * 0.54)))
    if lang == "en":
        return "\n".join(textwrap.wrap(text, width=cells, break_long_words=True,
                                     break_on_hyphens=False))
    lines, line, used = [], "", 0
    for char in text:
        cost = 2 if unicodedata.east_asian_width(char) in ("W", "F") else 1
        if line and used + cost > cells:
            lines.append(line)
            line, used = "", 0
        line += char
        used += cost
    if line:
        lines.append(line)
    return "\n".join(lines)


def make_srt(captions, lang, width, height):
    blocks = []
    for caption in captions:
        if caption[lang]:
            text = wrap_caption(caption[lang], lang, width, height)
            blocks.append(f"{len(blocks) + 1}\n{srt_time(caption['start'])} --> "
                          f"{srt_time(caption['end'])}\n{text}\n")
    return "\n".join(blocks)


def choose_font(warnings):
    executable = shutil.which("fc-match")
    if executable:
        family = run([executable, "-f", "%{family}", "Noto Sans CJK SC:lang=zh-cn"])
        family = family.split(",")[0].strip()
        # Font names enter a filter value: allow only an unambiguous safe subset.
        if family and re.fullmatch(r"[\w ()-]+", family, flags=re.UNICODE):
            if "Noto Sans CJK" not in family:
                warnings.append(f"Noto Sans CJK SC was not selected; using {family}. "
                                "Check Chinese glyphs in the rendered preview.")
            return family
    warnings.append("Could not verify a CJK font; requested Noto Sans CJK SC. "
                    "Check Chinese glyphs before publishing.")
    return "Noto Sans CJK SC"


def ffmpeg_base(ffmpeg):
    return [ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
            "-filter_threads", "1", "-filter_complex_threads", "1"]


def render_segments(spec, temporary, ffmpeg, preset):
    width, height, fps = spec["width"], spec["height"], spec["fps"]
    if spec["fit"] == "contain":
        geometry = (f"scale={width}:{height}:force_original_aspect_ratio=decrease:"
                    f"force_divisible_by=2,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2")
    else:
        geometry = (f"scale={width}:{height}:force_original_aspect_ratio=increase:"
                    f"force_divisible_by=2,crop={width}:{height}")
    paths = []
    for index, clip in enumerate(spec["clips"]):
        print(f"Rendering clip {index + 1}/{len(spec['clips'])}...", flush=True)
        duration = clip["render_end"] - clip["render_start"]
        requested_duration = clip["out"] - clip["in"]
        # Pad a final video frame when frame rounding needs a fraction more time.
        video_filter = (f"trim=duration={decimal(requested_duration)},setpts=PTS-STARTPTS,"
                        f"{geometry},setsar=1,fps={decimal(fps)},"
                        f"tpad=stop_mode=clone:stop_duration={decimal(2 / fps)},"
                        f"trim=end_frame={clip['frames']},setpts=N/({decimal(fps)}*TB),"
                        "format=yuv420p")
        command = ffmpeg_base(ffmpeg) + ["-threads", "2", "-ss", decimal(clip["in"]),
                                       "-i", clip["source"]]
        if clip["audio_stream"] is None:
            command += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
            audio_map = "1:a:0"
        else:
            audio_map = f"0:{clip['audio_stream']}"
        # PCM intermediates avoid repeating AAC encoder delay at every cut.
        name = f"segment-{index:06d}.mkv"
        command += [
            "-map", f"0:{clip['video_stream']}", "-map", audio_map,
            "-vf", video_filter, "-af",
            f"atrim=duration={decimal(requested_duration)},asetpts=PTS-STARTPTS,"
            "aresample=48000:async=1:first_pts=0,aformat=channel_layouts=stereo,"
            f"apad,atrim=duration={decimal(duration)}",
            "-t", decimal(duration), "-c:v", "libx264", "-preset", preset,
            "-crf", "20", "-threads", "2", "-pix_fmt", "yuv420p",
            "-c:a", "pcm_s16le", "-ar", "48000", "-ac", "2",
            "-map_metadata", "-1", "-metadata:s:v:0", "rotate=0", name,
        ]
        run(command, cwd=temporary)
        paths.append((name, duration))
    # Only generated safe filenames appear inside the concat file.
    (temporary / "segments.ffconcat").write_text(
        "ffconcat version 1.0\n" + "".join(
            f"file '{name}'\nduration {decimal(duration)}\n" for name, duration in paths
        ), encoding="utf-8",
    )
    run(ffmpeg_base(ffmpeg) + [
        "-f", "concat", "-safe", "1", "-i", "segments.ffconcat", "-map", "0:v:0",
        "-map", "0:a:0", "-c:v", "copy", "-af",
        "aresample=48000:async=1:first_pts=0", "-c:a", "aac", "-b:a", "192k",
        "-ar", "48000", "-ac", "2", "-t", decimal(spec["render_duration"]),
        "-movflags", "+faststart", "assembled.mp4",
    ], cwd=temporary)


def create_master(spec, temporary, ffmpeg):
    music = spec["music"]
    if not music:
        shutil.copyfile(temporary / "assembled.mp4", temporary / "master.mp4")
        return
    limiter_help = run([ffmpeg, "-hide_banner", "-h", "filter=alimiter"])
    latency_supported = bool(re.search(r"^\s*latency\s+", limiter_help, re.MULTILINE))
    # Older FFmpeg builds have the limiter, but not its latency compensation
    # option. Their minimum 0.1 ms attack keeps lookahead below 1 ms. Explicitly
    # disable auto level on both paths so mixing cannot boost the entire track.
    limiter = "alimiter=limit=0.95:level=false"
    if latency_supported:
        limiter += ":latency=true"
        music["limiter"] = {"auto_level": False, "latency_compensated": True}
    else:
        limiter += ":attack=0.1"
        music["limiter"] = {"auto_level": False, "latency_compensated": False,
                            "attack_ms": 0.1, "lookahead_ms_upper_bound": 1}
        spec["warnings"].append(
            "This FFmpeg lacks alimiter latency compensation; music mixing uses "
            "0.1 ms attack (lookahead below 1 ms), with automatic level boost disabled."
        )
    fades = ""
    if music["fade_in"]:
        fades += f",afade=t=in:d={decimal(music['fade_in'])}"
    if music["fade_out"]:
        length = min(music["fade_out"], spec["render_duration"])
        fades += f",afade=t=out:st={decimal(spec['render_duration'] - length)}:d={decimal(length)}"
    graph = (
        f"[0:a:0]volume={decimal(music['original_volume'])}[original];"
        f"[1:{music['audio_stream']}]aresample=48000,aformat=channel_layouts=stereo,"
        f"volume={decimal(music['volume'])}{fades}[music];"
        "[original][music]amix=inputs=2:duration=first:dropout_transition=0:normalize=0,"
        f"{limiter}[a]"
    )
    run(ffmpeg_base(ffmpeg) + [
        "-i", "assembled.mp4", "-stream_loop", "-1", "-i", music["source"],
        "-filter_complex", graph, "-map", "0:v:0", "-map", "[a]", "-c:v", "copy",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
        "-t", decimal(spec["render_duration"]), "-movflags", "+faststart", "master.mp4",
    ], cwd=temporary)


def subtitle_versions(spec, temporary, ffmpeg, preset, font):
    versions = {}
    for lang in ("zh", "en"):
        srt = make_srt(spec["captions"], lang, spec["width"], spec["height"])
        (temporary / f"{lang}.srt").write_text(srt, encoding="utf-8")
        if not srt:
            shutil.copyfile(temporary / "master.mp4", temporary / f"{lang}.mp4")
            versions[lang] = {"subtitles": False, "note": "No captions in this language; copied master."}
            spec["warnings"].append(f"No {lang} captions; {lang}.mp4 is a copy of master.mp4.")
            continue
        print(f"Rendering {lang} subtitles...", flush=True)
        # libass defaults to a 384x288 script coordinate space for SRT input.
        # Height-relative values therefore remain consistent between preview/full.
        style = (f"Fontname={font},Fontsize=10.4,PrimaryColour=&H00FFFFFF,"
                 "OutlineColour=&H00202020,BorderStyle=1,Outline=0.65,Shadow=0.35,"
                 "Alignment=2,MarginV=23,MarginL=12,MarginR=12")
        # The filename is generated, relative, ASCII and constant; source paths
        # and user caption text never enter FFmpeg's filter-expression syntax.
        subtitle_filter = f"subtitles=filename={lang}.srt:force_style='{style}'"
        run(ffmpeg_base(ffmpeg) + [
            "-i", "master.mp4", "-map", "0:v:0", "-map", "0:a:0",
            "-vf", subtitle_filter, "-c:v", "libx264", "-preset", preset,
            "-crf", "20", "-threads", "2", "-pix_fmt", "yuv420p", "-c:a", "copy",
            "-movflags", "+faststart", f"{lang}.mp4",
        ], cwd=temporary)
        versions[lang] = {"subtitles": True,
                          "caption_count": sum(bool(c[lang]) for c in spec["captions"])}
    return versions


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan", type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--preview", action="store_true")
    arguments = parser.parse_args()
    ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        raise RenderError("ffmpeg and ffprobe must already be installed and on PATH")
    plan_path = arguments.plan.expanduser().resolve(strict=True)
    try:
        plan = json.loads(plan_path.read_text(encoding="utf-8-sig"),
                          parse_constant=lambda value: (_ for _ in ()).throw(
                              ValueError(f"Invalid JSON number: {value}")))
    except (ValueError, UnicodeError) as exc:
        raise RenderError(f"Cannot read plan JSON: {exc}") from exc
    spec = validate(plan, plan_path.parent, ffprobe, arguments.preview)
    if any(c["zh"] or c["en"] for c in spec["captions"]):
        filters = run([ffmpeg, "-hide_banner", "-filters"])
        if not re.search(r"\bsubtitles\s+V->V\b", filters):
            raise RenderError("This FFmpeg has no subtitles filter; a libass-enabled build is required")
    encoders = run([ffmpeg, "-hide_banner", "-encoders"])
    if not re.search(r"\blibx264\b", encoders):
        raise RenderError("This FFmpeg has no libx264 encoder")
    out = arguments.out.expanduser().absolute()
    if out.is_symlink():
        raise RenderError("Output directory must not be a symlink")
    if out.exists() and (not out.is_dir() or any(out.iterdir())):
        raise RenderError(f"Output must be a new or empty directory; refusing to overwrite: {out}")
    out.mkdir(parents=True, exist_ok=True)
    preset = "ultrafast" if arguments.preview else "veryfast"
    font = choose_font(spec["warnings"])
    with tempfile.TemporaryDirectory(prefix=".storytelling-render-", dir=out.parent) as work:
        temporary = Path(work)
        render_segments(spec, temporary, ffmpeg, preset)
        create_master(spec, temporary, ffmpeg)
        versions = subtitle_versions(spec, temporary, ffmpeg, preset, font)
        rendered = {}
        for name in ("master.mp4", "zh.mp4", "en.mp4"):
            metadata = probe(temporary / name, ffprobe, {})
            video, audio = first_stream(metadata, "video"), first_stream(metadata, "audio")
            if not video or not audio:
                raise RenderError(f"Output verification failed: {name} lacks video or audio")
            duration = media_duration(metadata, video)
            if duration is None or abs(duration - spec["render_duration"]) > 2 / spec["fps"] + 0.05:
                raise RenderError(f"Output verification failed: unexpected duration for {name}")
            if video.get("width") != spec["width"] or video.get("height") != spec["height"]:
                raise RenderError(f"Output verification failed: unexpected dimensions for {name}")
            rendered[name] = {"duration": duration, "bytes": (temporary / name).stat().st_size}
        manifest = {
            "version": 1, "title": plan["title"],
            "created_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
            "preview": arguments.preview, "plan_path": str(plan_path),
            "output": {key: spec[key] for key in ("width", "height", "fps", "fit")},
            "planned_duration": spec["planned_duration"], "render_duration": spec["render_duration"],
            "clips": spec["clips"], "captions": spec["captions"], "music": spec["music"],
            "subtitle_font": font, "versions": versions, "files": rendered,
            "warnings": spec["warnings"], "ffmpeg_version": run([ffmpeg, "-version"]).splitlines()[0],
        }
        (temporary / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (temporary / "plan.snapshot.json").write_text(
            json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        # Recheck after rendering, and publish with exclusive creation. Never
        # replace files which another process may have added during the render.
        if any(out.iterdir()):
            raise RenderError("Output directory became nonempty during rendering; no files were overwritten")
        names = ("master.mp4", "zh.mp4", "en.mp4", "zh.srt", "en.srt",
                 "manifest.json", "plan.snapshot.json")
        published = []
        try:
            for name in names:
                with (out / name).open("xb") as destination:
                    published.append(out / name)
                    with (temporary / name).open("rb") as source:
                        shutil.copyfileobj(source, destination)
        except BaseException:
            for path in published:
                path.unlink(missing_ok=True)
            raise
    print(f"Rendered successfully: {out}")
    for warning in spec["warnings"]:
        print(f"Warning: {warning}", file=sys.stderr)


if __name__ == "__main__":
    try:
        main()
    except (RenderError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("Rendering cancelled.", file=sys.stderr)
        sys.exit(130)
