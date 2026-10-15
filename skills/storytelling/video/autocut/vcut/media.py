"""FFmpeg / ffprobe helpers (cross-platform, no shell)."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Sequence

VIDEO_EXT = {".mp4", ".mov", ".m4v", ".mkv", ".avi", ".mts", ".m2ts", ".webm", ".3gp"}
AUDIO_EXT = {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wma"}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".heic", ".gif"}
RAW360_EXT = {".insv", ".insp"}
PROXY_EXT = {".lrv"}
SKIP_NAMES = {"thumbs.db", ".ds_store", "desktop.ini"}


class FFmpegError(RuntimeError):
    pass


def ffmpeg_bin() -> str:
    return os.environ.get("VCUT_FFMPEG") or shutil.which("ffmpeg") or "ffmpeg"


def ffprobe_bin() -> str:
    return os.environ.get("VCUT_FFPROBE") or shutil.which("ffprobe") or "ffprobe"


def run(cmd: Sequence[str], cwd: Path | None = None, capture: bool = True, check: bool = True,
        input_bytes: bytes | None = None) -> subprocess.CompletedProcess:
    kwargs: dict[str, Any] = {}
    if os.name == "nt":  # don't pop up console windows when called from GUI agents
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    proc = subprocess.run(
        list(cmd), cwd=str(cwd) if cwd else None, input=input_bytes,
        stdout=subprocess.PIPE if capture else None, stderr=subprocess.PIPE if capture else None,
        **kwargs,
    )
    if check and proc.returncode != 0:
        err = (proc.stderr or b"").decode("utf-8", "replace")[-3000:]
        raise FFmpegError(f"命令失败 ({proc.returncode}): {' '.join(map(str, cmd))[:400]}\n{err}")
    return proc


def ffmpeg(args: Sequence[str], cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess:
    return run([ffmpeg_bin(), "-hide_banner", "-nostdin", "-y", *map(str, args)], cwd=cwd, check=check)


def ffprobe_json(path: Path) -> dict:
    proc = run([ffprobe_bin(), "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)])
    return json.loads(proc.stdout.decode("utf-8", "replace") or "{}")


def _rotation(stream: dict) -> int:
    rot = 0
    tags = stream.get("tags") or {}
    if "rotate" in tags:
        try:
            rot = int(float(tags["rotate"]))
        except ValueError:
            rot = 0
    for sd in stream.get("side_data_list") or []:
        if "rotation" in sd:
            try:
                rot = int(float(sd["rotation"]))
            except (TypeError, ValueError):
                pass
    return rot % 360


def _fps(stream: dict) -> float:
    for key in ("avg_frame_rate", "r_frame_rate"):
        v = stream.get(key) or "0/0"
        try:
            num, den = v.split("/")
            if float(den) > 0 and float(num) > 0:
                return round(float(num) / float(den), 3)
        except ValueError:
            continue
    return 0.0


@dataclass
class ProbeInfo:
    path: str
    kind: str  # video | audio | image | raw360 | proxy | other
    duration: float = 0.0
    width: int = 0
    height: int = 0
    fps: float = 0.0
    rotation: int = 0
    vcodec: str = ""
    acodec: str = ""
    has_audio: bool = False
    has_video: bool = False
    bit_depth: int = 8
    color_transfer: str = ""
    creation_time: str = ""
    size: int = 0
    tags: dict[str, str] = field(default_factory=dict)

    @property
    def display_size(self) -> tuple[int, int]:
        if self.rotation in (90, 270):
            return self.height, self.width
        return self.width, self.height

    @property
    def orientation(self) -> str:
        w, h = self.display_size
        if not w or not h:
            return "unknown"
        return "portrait" if h > w else "landscape"

    def to_dict(self) -> dict:
        d = self.__dict__.copy()
        d["display_width"], d["display_height"] = self.display_size
        d["orientation"] = self.orientation
        return d


def kind_of(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in VIDEO_EXT:
        return "video"
    if ext in AUDIO_EXT:
        return "audio"
    if ext in IMAGE_EXT:
        return "image"
    if ext in RAW360_EXT:
        return "raw360"
    if ext in PROXY_EXT:
        return "proxy"
    return "other"


def probe(path: Path) -> ProbeInfo:
    path = Path(path)
    kind = kind_of(path)
    info = ProbeInfo(path=str(path), kind=kind, size=path.stat().st_size if path.exists() else 0)
    if kind in ("other",):
        return info
    try:
        data = ffprobe_json(path)
    except FFmpegError:
        return info
    fmt = data.get("format") or {}
    tags: dict[str, str] = {}
    for k, v in (fmt.get("tags") or {}).items():
        tags[k] = str(v)
    try:
        info.duration = float(fmt.get("duration") or 0)
    except ValueError:
        info.duration = 0.0
    for st in data.get("streams") or []:
        ctype = st.get("codec_type")
        for k, v in (st.get("tags") or {}).items():
            tags.setdefault(f"{ctype}:{k}", str(v))
        if ctype == "video" and not info.has_video:
            if (st.get("disposition") or {}).get("attached_pic"):
                continue
            info.has_video = True
            info.width = int(st.get("width") or 0)
            info.height = int(st.get("height") or 0)
            info.fps = _fps(st)
            info.rotation = _rotation(st)
            info.vcodec = st.get("codec_name", "")
            info.color_transfer = st.get("color_transfer", "") or ""
            pix = st.get("pix_fmt", "") or ""
            info.bit_depth = 10 if ("10" in pix or "p010" in pix) else 8
            if not info.duration:
                try:
                    info.duration = float(st.get("duration") or 0)
                except ValueError:
                    pass
        elif ctype == "audio" and not info.has_audio:
            info.has_audio = True
            info.acodec = st.get("codec_name", "")
    info.tags = tags
    info.creation_time = tags.get("creation_time") or tags.get("video:creation_time") or ""
    if kind == "image":
        info.duration = 0.0
    return info


@lru_cache(maxsize=None)
def has_encoder(name: str) -> bool:
    """Actually try to encode a few frames: NVENC is often *listed* but unusable (no GPU/driver)."""
    try:
        proc = ffmpeg(["-f", "lavfi", "-i", "color=c=black:s=256x256:d=0.2", "-frames:v", "3",
                       "-c:v", name, "-f", "null", "-"], check=False)
        return proc.returncode == 0
    except FileNotFoundError:
        return False


def pick_encoder(pref: str = "auto") -> str:
    if pref and pref != "auto":
        if has_encoder(pref):
            return pref
    for cand in ("h264_nvenc", "libx264"):
        if has_encoder(cand):
            return cand
    return "libx264"


def video_encode_args(encoder: str, quality: dict | None = None, fast: bool = False) -> list[str]:
    q = quality or {}
    if "nvenc" in encoder:
        return ["-c:v", encoder, "-preset", "p4" if not fast else "p1", "-tune", "hq", "-rc", "vbr",
                "-cq", str(q.get("nvenc_cq", 23)), "-b:v", "0", "-pix_fmt", "yuv420p"]
    return ["-c:v", "libx264", "-preset", "veryfast" if fast else q.get("preset_x264", "medium"),
            "-crf", str(q.get("crf", 20)), "-pix_fmt", "yuv420p"]


def hwaccel_args(mode: str = "auto") -> list[str]:
    if mode in ("", "none", None):
        return []
    return ["-hwaccel", mode]


EQUIRECT_KEYFRAME_VF = ("split[a][b];[a]v360=e:flat:yaw=0:pitch=-5:h_fov=100:v_fov=62:w=960:h=540[f];"
                        "[b]v360=e:flat:yaw=180:pitch=-5:h_fov=100:v_fov=62:w=960:h=540[r];[f][r]hstack=2")


def is_equirect_size(w: int | None, h: int | None) -> bool:
    """2:1 panorama (already-stitched 360° export) — at least 1920 wide."""
    return bool(w and h and w >= 1920 and abs(w / h - 2.0) < 0.02)


def extract_frame(src: Path, t: float, out: Path, width: int = 640, hwaccel: str = "none",
                  equirect: bool = False) -> Path:
    """Grab one JPEG. For 360° equirect sources the keyframe is a front|back perspective pair
    (so vision models see a normal picture instead of a stretched panorama)."""
    out.parent.mkdir(parents=True, exist_ok=True)
    vf = f"scale={width}:-2"
    if equirect:
        vf = f"{EQUIRECT_KEYFRAME_VF},scale={max(width, 640) * 2}:-2"
    ffmpeg([*hwaccel_args(hwaccel), "-ss", f"{max(0.0, t):.3f}", "-i", str(src), "-frames:v", "1",
            "-vf", vf, "-q:v", "3", str(out)])
    return out


def extract_audio_wav(src: Path, out: Path, sr: int = 16000) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg(["-i", str(src), "-vn", "-ac", "1", "-ar", str(sr), "-c:a", "pcm_s16le", str(out)])
    return out


def make_proxy(src: Path, out: Path, height: int = 360, fps: int = 10) -> Path:
    """Small low-res proxy for uploading to cloud vision models."""
    out.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg(["-i", str(src), "-vf", f"scale=-2:{height},fps={fps}", "-c:v", "libx264", "-preset", "veryfast",
            "-crf", "32", "-c:a", "aac", "-b:a", "48k", "-ac", "1", str(out)])
    return out
