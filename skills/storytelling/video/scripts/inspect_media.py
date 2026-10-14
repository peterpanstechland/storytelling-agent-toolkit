#!/usr/bin/env python3
"""Build a sparse, timestamped visual index without modifying source videos.

Requires Python 3, Pillow, ffmpeg and ffprobe. Standard output is one JSON
summary; detailed metadata, per-file errors and warnings live in manifest.json.
"""

import argparse
import datetime as dt
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys


EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".m4v", ".avi"}
INDEX_WARNING = (
    "这是稀疏视觉索引，不代表已审看全部内容；短暂动作和精彩瞬间可能落在采样帧之间。"
    "长片尤其需要对候选时间段加密采样或播放复核。"
)


def finite_number(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (ValueError, TypeError):
        return None


def positive_number(value):
    result = finite_number(value)
    return result if result is not None and result > 0 else None


def positive_float(value):
    number = positive_number(value)
    if number is None:
        raise argparse.ArgumentTypeError("must be a finite number greater than zero")
    return number


def frame_limit(value):
    try:
        number = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer between 1 and 24") from exc
    if not 1 <= number <= 24:
        raise argparse.ArgumentTypeError("must be an integer between 1 and 24")
    return number


def absolute_path(value):
    # Do not resolve links before checking whether the input is a symlink.
    return Path(os.path.abspath(os.path.expanduser(value)))


def contains_path(parent, child):
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def symlink_component(path):
    return next((part for part in [path, *path.parents] if part.is_symlink()), None)


def error_entry(stage, message, source=None):
    entry = {"stage": stage, "message": str(message)}
    if source is not None:
        entry["source"] = str(source)
    return entry


def collect_sources(input_path, output_path):
    errors = []
    skipped_links = []
    if input_path.is_file():
        if input_path.suffix.lower() not in EXTENSIONS:
            raise ValueError("输入文件格式不支持；支持 mp4/mov/mkv/webm/m4v/avi。")
        return [input_path], errors, skipped_links

    sources = []

    def walk_error(exc):
        errors.append(error_entry("scan", exc, getattr(exc, "filename", input_path)))

    for root, directories, filenames in os.walk(input_path, followlinks=False, onerror=walk_error):
        root_path = Path(root)
        kept = []
        for name in sorted(directories):
            directory = root_path / name
            if directory.is_symlink():
                skipped_links.append(str(directory))
            elif not contains_path(output_path, directory):
                kept.append(name)
        directories[:] = kept
        for name in sorted(filenames):
            candidate = root_path / name
            if candidate.is_symlink():
                skipped_links.append(str(candidate))
            elif candidate.suffix.lower() in EXTENSIONS and candidate.is_file():
                sources.append(candidate)
    return sorted(sources, key=lambda item: str(item).casefold()), errors, skipped_links


def run_command(command, timeout):
    try:
        result = subprocess.run(
            command, stdin=subprocess.DEVNULL, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout, check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("处理超时（{} 秒），请检查该素材或用较短片段重试。".format(timeout)) from exc
    if result.returncode:
        detail = "\n".join(result.stderr.strip().splitlines()[-12:])
        raise RuntimeError(detail or "命令退出码 {}".format(result.returncode))
    return result


def bit_depth(stream):
    explicit = positive_number(stream.get("bits_per_raw_sample"))
    if explicit:
        return int(explicit)
    pixel_format = stream.get("pix_fmt", "")
    match = re.search(r"(?:p0?|gray)(9|10|12|14|16)(?:le|be)?$", pixel_format)
    if match:
        return int(match.group(1))
    if pixel_format in {"rgb48le", "rgb48be", "bgr48le", "bgr48be", "rgba64le", "rgba64be"}:
        return 16
    if pixel_format.startswith(("yuv", "yuva", "rgb", "bgr", "gbr", "gray", "nv")):
        return 8
    return None


def probe_media(source, ffprobe):
    result = run_command([
        ffprobe, "-v", "error", "-show_format", "-show_streams", "-of", "json", str(source),
    ], timeout=30)
    raw = json.loads(result.stdout)
    streams = raw.get("streams", [])
    videos = [item for item in streams if item.get("codec_type") == "video"
              and not item.get("disposition", {}).get("attached_pic")]
    if not videos:
        raise ValueError("文件中没有可采样的视频轨道。")
    video = next((item for item in videos if item.get("disposition", {}).get("default")), videos[0])
    file_info = raw.get("format", {})
    duration = positive_number(file_info.get("duration")) or positive_number(video.get("duration"))
    if duration is None:
        raise ValueError("无法取得有效时长，不能可靠地均匀采样。")
    container_start = finite_number(file_info.get("start_time")) or 0.0
    video_start = finite_number(video.get("start_time"))
    if video_start is None:
        video_start = container_start
    sampling_start = max(0.0, video_start - container_start)
    available_duration = max(0.0, duration - sampling_start)
    video_duration = positive_number(video.get("duration"))
    duration_note = None
    # Some containers with a nonzero timestamp origin report the ending PTS
    # as format.duration. Verify the tail packets without decoding the video.
    if video_duration is None and abs(container_start) > 0.001:
        try:
            tail = run_command([
                ffprobe, "-v", "error", "-read_intervals", "{:.9f}%".format(container_start + duration),
                "-select_streams", str(video["index"]), "-show_packets",
                "-show_entries", "packet=pts_time,duration_time", "-of", "json", str(source),
            ], timeout=30)
            packet_ends = []
            for packet in json.loads(tail.stdout).get("packets", []):
                pts = finite_number(packet.get("pts_time"))
                if pts is not None:
                    packet_ends.append(pts + (positive_number(packet.get("duration_time")) or 0.0))
            if packet_ends and max(packet_ends) > video_start:
                video_duration = max(packet_ends) - video_start
                available_duration = max(packet_ends) - container_start - sampling_start
                duration_note = "video duration verified from tail packet timestamps"
        except (RuntimeError, ValueError, OSError):
            duration_note = "tail duration could not be verified; using container metadata"
    video_duration = video_duration or available_duration
    sampling_duration = min(video_duration, available_duration)
    if sampling_duration <= 0:
        raise ValueError("视频轨道时长或开始时间无效，不能可靠地采样。")
    rotation = finite_number(video.get("tags", {}).get("rotate")) or 0.0
    side_data = video.get("side_data_list", [])
    for item in side_data:
        side_rotation = finite_number(item.get("rotation"))
        if side_rotation is not None:
            rotation = side_rotation
            break
    width, height = int(video.get("width", 0)), int(video.get("height", 0))
    if width <= 0 or height <= 0:
        raise ValueError("视频宽高无效。")
    depth = bit_depth(video)
    hdr = video.get("color_transfer") in {"smpte2084", "arib-std-b67"} or any(
        "mastering display" in item.get("side_data_type", "").lower()
        or "content light" in item.get("side_data_type", "").lower() for item in side_data
    )
    return {
        "duration": duration,
        "video_duration": video_duration,
        "duration_note": duration_note,
        "width": width,
        "height": height,
        "rotation": rotation,
        "has_audio": any(item.get("codec_type") == "audio" for item in streams),
        "video_stream_index": video["index"],
        "codec": video.get("codec_name"),
        "pixel_format": video.get("pix_fmt"),
        "bit_depth": depth,
        "is_10bit_or_higher": depth is not None and depth >= 10,
        "is_hdr": hdr,
        "color_transfer": video.get("color_transfer"),
        "color_primaries": video.get("color_primaries"),
        "color_space": video.get("color_space"),
        "sample_aspect_ratio": video.get("sample_aspect_ratio"),
        "average_frame_rate": video.get("avg_frame_rate"),
        "container_start_time": container_start,
        "video_start_time": video_start,
        "sampling_start_seconds": sampling_start,
        "sampling_duration_seconds": sampling_duration,
    }


def sample_times(probe, interval, max_frames):
    duration = probe["sampling_duration_seconds"]
    count = max(1, min(max_frames, math.ceil(duration / interval)))
    # An odd number of equally spaced bin centres includes the exact midpoint.
    if count % 2 == 0:
        count = count + 1 if count < max_frames else count - 1
    start = probe["sampling_start_seconds"]
    return [start + duration * (index + 0.5) / count for index in range(count)]


def timecode(seconds):
    milliseconds = max(0, round(seconds * 1000))
    seconds, millis = divmod(milliseconds, 1000)
    minutes, second = divmod(seconds, 60)
    hours, minute = divmod(minutes, 60)
    return "{:02d}:{:02d}:{:02d}.{:03d}".format(hours, minute, second, millis)


def extract_frame(source, probe, requested, destination, ffmpeg):
    # copyts preserves the source PTS in showinfo. Input -ss is relative to the
    # container start; subtract that origin when reporting the extracted frame.
    result = run_command([
        ffmpeg, "-hide_banner", "-loglevel", "info", "-nostdin", "-n",
        "-copyts", "-ss", "{:.9f}".format(requested), "-i", str(source),
        "-map", "0:{}".format(probe["video_stream_index"]),
        "-frames:v", "1", "-an", "-sn", "-dn", "-vsync", "0",
        "-vf", "scale=360:max(2\\,trunc(360/dar/2)*2),setsar=1,showinfo",
        "-q:v", "3", "-update", "1", str(destination),
    ], timeout=90)
    frame_match = re.search(r"\[Parsed_showinfo[^\]]*\].*?\bn:\s*0\s+pts:\s*(-?\d+)\s+pts_time:", result.stderr)
    time_base_match = re.search(r"\[Parsed_showinfo[^\]]*\].*?config in time_base:\s*(\d+)/(\d+)", result.stderr)
    # showinfo's human-readable pts_time rounds large timestamps; retain the
    # integer PTS and rational time base for accurate long-video labels.
    actual_pts = None
    if frame_match and time_base_match and int(time_base_match.group(2)):
        actual_pts = int(frame_match.group(1)) * int(time_base_match.group(1)) / int(time_base_match.group(2))
    if not destination.is_file() or destination.stat().st_size == 0:
        raise RuntimeError("FFmpeg 未生成画面；所选时间点可能无法解码。")
    if actual_pts is None:
        destination.unlink()
        raise RuntimeError("无法读取实际帧时间戳，未将请求时间冒充实际时间。")
    timestamp = actual_pts - probe["container_start_time"]
    return {
        "requested_time_seconds": round(requested, 9),
        "timestamp_seconds": round(timestamp, 9),
        "timecode": timecode(timestamp),
        "source_pts_seconds": actual_pts,
        "source_pts": int(frame_match.group(1)),
        "source_time_base": "{}/{}".format(*time_base_match.groups()),
        "frame": str(destination),
    }


def select_font(ImageFont, size):
    cjk_candidates = [
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansSC-Regular.ttf",
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
        "/System/Library/Fonts/PingFang.ttc",
        "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/simhei.ttf",
    ]
    fallback_candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/Library/Fonts/Arial Unicode.ttf",
        "C:/Windows/Fonts/arial.ttf",
    ]
    for candidate in cjk_candidates + fallback_candidates:
        if Path(candidate).is_file():
            try:
                return ImageFont.truetype(candidate, size), candidate in cjk_candidates, candidate
            except OSError:
                pass
    return ImageFont.load_default(), False, None


def wrap_text(text, draw, font, width):
    lines, line = [], ""
    for char in text:
        candidate = line + char
        box = draw.textbbox((0, 0), candidate, font=font)
        if line and box[2] - box[0] > width:
            lines.append(line)
            line = char
        else:
            line = candidate
    if line:
        lines.append(line)
    return lines or [""]


def make_contact_sheet(source, frames, destination, image_modules):
    Image, ImageDraw, ImageFont = image_modules
    title_font, supports_cjk, font_path = select_font(ImageFont, 25)
    label_font, _, _ = select_font(ImageFont, 19)
    columns, cell_width, image_height, label_height, gap = 4, 360, 240, 34, 16
    width = columns * cell_width + (columns + 1) * gap
    title = source.name.replace("\n", " ").replace("\r", " ").replace("\t", " ")
    if not supports_cjk:
        title = title.encode("ascii", "backslashreplace").decode("ascii")
    scratch = Image.new("RGB", (width, 1))
    scratch_draw = ImageDraw.Draw(scratch)
    title_lines = wrap_text(title, scratch_draw, title_font, width - 2 * gap)
    header_height = 26 + len(title_lines) * 35 + 29
    rows = math.ceil(len(frames) / columns)
    height = header_height + rows * (image_height + label_height + gap) + gap
    sheet = Image.new("RGB", (width, height), "#14171d")
    draw = ImageDraw.Draw(sheet)
    for index, line in enumerate(title_lines):
        draw.text((gap, 15 + 35 * index), line, font=title_font, fill="#f4f5f7")
    draw.text((gap, header_height - 28), "SPARSE INDEX / source time HH:MM:SS.mmm / review candidates in motion",
              font=label_font, fill="#b9c4d3")
    for index, frame in enumerate(frames):
        x = gap + (index % columns) * (cell_width + gap)
        y = header_height + (index // columns) * (image_height + label_height + gap)
        draw.rectangle((x, y, x + cell_width, y + image_height), fill="#252c36")
        with Image.open(frame["frame"]) as thumbnail:
            thumbnail = thumbnail.convert("RGB")
            resampling = getattr(Image, "Resampling", Image)
            thumbnail.thumbnail((cell_width, image_height), resampling.LANCZOS)
            sheet.paste(thumbnail, (x + (cell_width - thumbnail.width) // 2,
                                    y + (image_height - thumbnail.height) // 2))
        draw.text((x + 4, y + image_height + 4), "{:02d}  {}".format(index + 1, frame["timecode"]),
                  font=label_font, fill="#e5edf8")
    sheet.save(destination, "JPEG", quality=90)
    return {"font": font_path, "cjk_font_available": supports_cjk}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", help="a video file or a directory to scan recursively")
    parser.add_argument("--out", required=True, help="a new or empty output directory")
    parser.add_argument("--interval", type=positive_float, default=15.0, help="target sampling interval in seconds (default: 15)")
    parser.add_argument("--max-frames", type=frame_limit, default=24, help="upper limit per file, 1–24 (default: 24)")
    arguments = parser.parse_args()
    try:
        from PIL import Image, ImageDraw, ImageFont
        input_path, output_path = absolute_path(arguments.input), absolute_path(arguments.out)
        linked = symlink_component(input_path)
        if linked is not None:
            raise ValueError("输入路径包含符号链接，不会跟随：{}".format(linked))
        if not input_path.exists() or not (input_path.is_file() or input_path.is_dir()):
            raise ValueError("输入路径不存在或不是普通文件/目录。")
        if symlink_component(output_path) is not None:
            raise ValueError("输出路径不能包含符号链接。")
        if output_path == input_path or contains_path(output_path, input_path):
            raise ValueError("输出目录不能等于输入目录或包含输入路径。")
        if output_path.exists() and (not output_path.is_dir() or any(output_path.iterdir())):
            raise ValueError("输出目录必须为空或尚不存在；不会覆盖已有结果。")
        ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
        if not ffmpeg or not ffprobe:
            raise ValueError("需要在 PATH 中提供 ffmpeg 和 ffprobe；此工具不会自动安装软件。")
        sources, scan_errors, skipped_links = collect_sources(input_path, output_path)
        output_path.mkdir(parents=True, exist_ok=True)
        if any(output_path.iterdir()):
            raise ValueError("输出目录已被其他程序写入，已停止以防覆盖。")
    except (ImportError, OSError, ValueError) as exc:
        print(json.dumps({"status": "error", "message": str(exc)}, ensure_ascii=False))
        return 2

    manifest = {
        "schema_version": 1,
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "input": str(input_path),
        "output": str(output_path),
        "sampling": {
            "target_interval_seconds": arguments.interval,
            "max_frames_per_file": arguments.max_frames,
            "method": "equally spaced bin centres; odd count to include midpoint",
            "timestamp_origin": "source container start; actual frame PTS minus container start_time",
            "thumbnail_width": 360,
        },
        "warnings": [INDEX_WARNING],
        "skipped_symlinks": skipped_links,
        "files": [],
        "errors": scan_errors,
    }
    if not sources:
        manifest["errors"].append(error_entry("scan", "没有找到支持的视频文件。"))
    for index, source in enumerate(sources, 1):
        record = {
            "id": "media_{:04d}".format(index), "source": str(source), "name": source.name,
            "probe": None, "frames": [], "contact_sheet": None, "warnings": [], "errors": [],
        }
        manifest["files"].append(record)
        try:
            record["probe"] = probe_media(source, ffprobe)
        except (RuntimeError, OSError, ValueError, KeyError) as exc:
            record["errors"].append(error_entry("probe", exc, source))
            continue
        if record["probe"]["is_hdr"] or record["probe"]["is_10bit_or_higher"]:
            record["warnings"].append(
                "检测到 HDR 或 10 bit 及以上素材。仅生成 JPEG 索引；未做 HDR 色调映射或色彩校准，"
                "缩略图不能用于判断原片最终色彩。"
            )
        folder = output_path / record["id"]
        folder.mkdir()
        for frame_index, requested in enumerate(sample_times(record["probe"], arguments.interval, arguments.max_frames), 1):
            destination = folder / "frame_{:03d}.jpg".format(frame_index)
            try:
                frame = extract_frame(source, record["probe"], requested, destination, ffmpeg)
                record["frames"].append(frame)
            except (RuntimeError, OSError, ValueError) as exc:
                failure = error_entry("frame", exc, source)
                failure["requested_time_seconds"] = requested
                record["errors"].append(failure)
        if record["frames"]:
            contact_sheet = folder / "contact_sheet.jpg"
            try:
                record["contact_sheet_rendering"] = make_contact_sheet(
                    source, record["frames"], contact_sheet, (Image, ImageDraw, ImageFont),
                )
                record["contact_sheet"] = str(contact_sheet)
                if not record["contact_sheet_rendering"]["cjk_font_available"]:
                    record["warnings"].append("未找到已知中文字体；联系表标题对非 ASCII 字符使用 Unicode 转义，完整文件名保留在清单中。")
            except (OSError, ValueError) as exc:
                record["errors"].append(error_entry("contact_sheet", exc, source))

    error_count = len(manifest["errors"]) + sum(len(item["errors"]) for item in manifest["files"])
    indexed = sum(bool(item["contact_sheet"]) for item in manifest["files"])
    status = "ok" if not error_count else ("partial" if indexed else "error")
    manifest["status"] = status
    manifest_path = output_path / "manifest.json"
    try:
        with manifest_path.open("x", encoding="utf-8") as handle:
            json.dump(manifest, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")
    except OSError as exc:
        print(json.dumps({"status": "error", "message": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps({
        "status": status, "manifest": str(manifest_path), "input_files": len(sources),
        "indexed_files": indexed, "sampled_frames": sum(len(item["frames"]) for item in manifest["files"]),
        "error_count": error_count, "skipped_symlinks": len(skipped_links), "warning": INDEX_WARNING,
    }, ensure_ascii=False))
    return 0 if status == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
