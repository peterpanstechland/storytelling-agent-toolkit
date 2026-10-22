"""Local music library (no bundled copyrighted music): mood tags + beat detection for 卡点."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import numpy as np

from . import config
from .media import AUDIO_EXT, ffmpeg_bin, probe
from .util import info, ok, read_json, short_hash, warn, write_json


def library_dir() -> Path | None:
    lib = (config.settings().get("music") or {}).get("library") or ""
    return Path(lib).expanduser() if lib else None


def _decode_mono(path: Path, sr: int = 22050, max_seconds: float = 600) -> np.ndarray:
    cmd = [ffmpeg_bin(), "-hide_banner", "-nostdin", "-v", "error", "-t", str(max_seconds), "-i", str(path),
           "-ac", "1", "-ar", str(sr), "-f", "f32le", "pipe:1"]
    raw = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True).stdout
    return np.frombuffer(raw, np.float32)


def detect_beats(path: Path) -> dict:
    """Return {"bpm": float, "beats": [t...], "method": str}. librosa if installed, else numpy onset/autocorr."""
    try:
        import librosa  # type: ignore

        y = _decode_mono(path)
        tempo, frames = librosa.beat.beat_track(y=y, sr=22050)
        beats = librosa.frames_to_time(frames, sr=22050).tolist()
        bpm = float(np.atleast_1d(tempo)[0])
        return {"bpm": round(bpm, 1), "beats": [round(b, 3) for b in beats], "method": "librosa"}
    except ImportError:
        pass
    sr, hop = 22050, 512
    y = _decode_mono(path, sr)
    if len(y) < sr * 2:
        return {"bpm": 0.0, "beats": [], "method": "numpy"}
    n_fft = 1024
    frames = np.lib.stride_tricks.sliding_window_view(y, n_fft)[::hop] * np.hanning(n_fft)
    spec = np.abs(np.fft.rfft(frames, axis=1))
    flux = np.maximum(0, np.diff(np.log1p(spec), axis=0)).sum(axis=1)
    flux = (flux - flux.mean()) / (flux.std() + 1e-9)
    fps = sr / hop
    ac = np.correlate(flux, flux, mode="full")[len(flux) - 1:]
    lo, hi = int(fps * 60 / 180), int(fps * 60 / 70)
    lag = lo + int(np.argmax(ac[lo:hi]))
    bpm = 60 * fps / lag
    # phase: offset maximizing onset energy on the grid
    phases = [flux[p::lag].sum() for p in range(lag)]
    phase = int(np.argmax(phases))
    beats = [round((phase + k * lag) / fps, 3) for k in range(int((len(flux) - phase) / lag) + 1)]
    return {"bpm": round(float(bpm), 1), "beats": beats, "method": "numpy"}


def scan_library(folder: Path | None = None, with_beats: bool = True) -> list[dict]:
    folder = folder or library_dir()
    if not folder or not folder.is_dir():
        warn("没有配置曲库目录（settings.yaml → music.library 或环境变量 VCUT_MUSIC_LIBRARY）。")
        return []
    index_path = folder / "library.json"
    old = {t["id"]: t for t in (read_json(index_path, {"tracks": []}) or {}).get("tracks", [])}
    manual = {}
    if (folder / "library.yaml").exists():
        manual = config.load_yaml(folder / "library.yaml") or {}
    tracks = []
    for f in sorted(folder.rglob("*")):
        if f.suffix.lower() not in AUDIO_EXT:
            continue
        tid = short_hash(f.relative_to(folder).as_posix(), f.stat().st_size)
        if tid in old:
            t = old[tid]
        else:
            pi = probe(f)
            tags = [p for p in f.relative_to(folder).parent.parts] + re.split(r"[\s_\-\[\]()（）]+", f.stem)
            t = {"id": tid, "path": f.relative_to(folder).as_posix(), "duration": round(pi.duration, 2),
                 "tags": [x for x in tags if x and not x.isdigit()]}
            if with_beats:
                try:
                    t.update(detect_beats(f))
                except Exception as e:  # noqa: BLE001
                    warn(f"节拍检测失败 {f.name}: {e}")
        extra = manual.get(f.name) or manual.get(t["path"]) or {}
        if extra.get("tags"):
            t["tags"] = sorted(set(t["tags"]) | set(extra["tags"]))
        if extra.get("license"):
            t["license"] = extra["license"]
        tracks.append(t)
        info(f"  ♪ {t['path']}  {t['duration']:.0f}s  bpm={t.get('bpm', '?')}  标签={','.join(t['tags'][:6])}")
    write_json(index_path, {"version": 1, "tracks": tracks})
    ok(f"曲库共 {len(tracks)} 首，索引写入 {index_path}")
    return tracks


def project_tracks(project_root: Path) -> list[dict]:
    out = []
    for f in sorted((project_root / "audio" / "music").glob("*")):
        if f.suffix.lower() in AUDIO_EXT:
            pi = probe(f)
            out.append({"id": "proj_" + short_hash(f.name), "abs_path": str(f.resolve()), "path": f.name,
                        "duration": pi.duration, "tags": ["project"], "source": "project"})
    return out


def pick_track(project_root: Path, moods: list[str], min_duration: float, prefer_file: str = "") -> dict | None:
    if prefer_file:
        p = Path(prefer_file)
        p = p if p.is_absolute() else project_root / p
        if p.exists():
            return {"abs_path": str(p.resolve()), "path": p.name, "duration": probe(p).duration, "tags": [], "source": "project"}
        warn(f"指定的配乐不存在：{prefer_file}")
    proj = project_tracks(project_root)
    if proj:
        t = max(proj, key=lambda t: t["duration"])
        return _with_beats(t)
    folder = library_dir()
    if not folder or not (folder / "library.json").exists():
        return None
    tracks = (read_json(folder / "library.json", {}) or {}).get("tracks", [])
    if not tracks:
        return None
    moods_l = [m.lower() for m in moods]

    def score(t: dict) -> float:
        tags = " ".join(t.get("tags", [])).lower()
        s = sum(2.0 for m in moods_l if m and m in tags)
        s += 1.0 if t.get("duration", 0) >= min_duration else -1.0
        return s
    best = max(tracks, key=lambda t: (score(t), t["id"]))
    best = dict(best)
    best["abs_path"] = str((folder / best["path"]).resolve())
    best["source"] = "library"
    return best


def _with_beats(t: dict) -> dict:
    cache = Path(t["abs_path"]).with_suffix(".beats.json")
    data = read_json(cache)
    if not data:
        try:
            data = detect_beats(Path(t["abs_path"]))
            write_json(cache, data)
        except Exception:  # noqa: BLE001
            data = {}
    return {**t, **(data or {})}
