"""One decode pass per clip: scene cuts (ffmpeg scene score) + quality signals (OpenCV)."""
from __future__ import annotations

import math
import re
import subprocess
import threading
from pathlib import Path

import cv2
import numpy as np

from ..media import ffmpeg_bin, hwaccel_args

_PTS_RE = re.compile(r"pts_time:([0-9.]+)")


def _analysis_size(dw: int, dh: int, width: int = 320) -> tuple[int, int]:
    if not dw or not dh:
        return width, int(width * 9 / 16) // 2 * 2
    h = max(2, int(round(width * dh / dw / 2)) * 2)
    return width, h


def scan_video(path: Path, display_w: int, display_h: int, *, scene_threshold: float = 0.32,
               sample_fps: float = 3.0, hwaccel: str = "auto") -> dict:
    """Return {"cuts": [t...], "frames": [{t, brightness, sharpness, dx, dy, over, under}]}."""
    w, h = _analysis_size(display_w, display_h)
    fc = (f"[0:v]scale={w}:{h},split[a][b];"
          f"[a]select='gt(scene,{scene_threshold})',showinfo[s];"
          f"[b]fps={sample_fps},format=gray[q]")
    cmd = [ffmpeg_bin(), "-hide_banner", "-nostdin", *hwaccel_args(hwaccel), "-i", str(path),
           "-filter_complex", fc, "-map", "[s]", "-f", "null", "-",
           "-map", "[q]", "-f", "rawvideo", "pipe:1"]
    kwargs = {}
    import os
    if os.name == "nt":
        kwargs["creationflags"] = 0x08000000
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kwargs)
    stderr_lines: list[str] = []

    def _drain():
        assert proc.stderr is not None
        for raw in proc.stderr:
            stderr_lines.append(raw.decode("utf-8", "replace"))

    t = threading.Thread(target=_drain, daemon=True)
    t.start()
    frame_bytes = w * h
    frames = []
    prev = None
    prev_g = None
    win = cv2.createHanningWindow((w, h), cv2.CV_32F)
    i = 0
    assert proc.stdout is not None
    while True:
        buf = proc.stdout.read(frame_bytes)
        if not buf or len(buf) < frame_bytes:
            break
        g = np.frombuffer(buf, np.uint8).reshape(h, w)
        f32 = g.astype(np.float32)
        lap = cv2.Laplacian(g, cv2.CV_64F).var()
        dx = dy = 0.0
        if prev is not None:
            (dx, dy), _resp = cv2.phaseCorrelate(prev, f32, win)
        frames.append({
            "t": round(i / sample_fps, 3),
            "brightness": float(g.mean() / 255.0),
            "sharpness": float(lap),
            "dx": float(dx) / w, "dy": float(dy) / h,
            "over": float((g > 250).mean()), "under": float((g < 8).mean()),
            "act": float(cv2.absdiff(g, prev_g).mean() / 255.0) if prev_g is not None else 0.0,
        })
        prev_g = g
        prev = f32
        i += 1
    proc.wait()
    t.join(timeout=5)
    for _stream in (proc.stdout, proc.stderr):
        if _stream is not None:
            _stream.close()
    if proc.returncode not in (0, None) and not frames:
        if hwaccel not in ("none", ""):
            return scan_video(path, display_w, display_h, scene_threshold=scene_threshold,
                              sample_fps=sample_fps, hwaccel="none")
        raise RuntimeError("ffmpeg 分析失败：" + "".join(stderr_lines[-15:]))
    cuts = []
    for line in stderr_lines:
        if "Parsed_showinfo" in line:
            m = _PTS_RE.search(line)
            if m:
                cuts.append(round(float(m.group(1)), 3))
    return {"cuts": sorted(set(cuts)), "frames": frames, "size": [w, h]}


def make_shots(duration: float, cuts: list[float], *, min_len: float = 0.6, max_len: float = 8.0) -> list[dict]:
    pts = [0.0] + [c for c in cuts if min_len <= c <= duration - min_len] + [duration]
    # merge too-short shots
    merged = [pts[0]]
    for p in pts[1:]:
        if p - merged[-1] >= min_len or p == duration:
            merged.append(p)
    if len(merged) >= 2 and merged[-1] - merged[-2] < min_len and len(merged) > 2:
        merged.pop(-2)
    shots = []
    for a, b in zip(merged[:-1], merged[1:]):
        n = max(1, math.ceil((b - a) / max_len - 1e-6))
        step = (b - a) / n
        for k in range(n):
            s, e = a + k * step, a + (k + 1) * step
            shots.append({"start": round(s, 3), "end": round(e, 3), "scene_cut": k == 0, "sub": k if n > 1 else None})
    for i, s in enumerate(shots):
        s["idx"] = i
    return shots


def shot_activity(frames: list[dict], start: float, end: float) -> dict:
    """Frame-difference energy inside a shot → mean activity + the action-peak time
    (used by the planner for speed ramps / freeze frames / punch-ins)."""
    sel = [f for f in frames if start <= f["t"] < end and "act" in f]
    if not sel:
        return {"activity": 0.0, "peak": 0.0, "peak_t": round((start + end) / 2, 3)}
    acts = np.array([f["act"] for f in sel])
    if len(acts) >= 3:
        acts = np.convolve(acts, np.ones(3) / 3, mode="same")
    k = int(np.argmax(acts))
    return {"activity": round(float(acts.mean()), 4), "peak": round(float(acts[k]), 4),
            "peak_t": round(float(sel[k]["t"]), 3)}


def _clip01(x: float) -> float:
    return float(max(0.0, min(1.0, x)))


def shot_quality(frames: list[dict], start: float, end: float) -> dict:
    sel = [f for f in frames if start <= f["t"] < end] or [min(frames, key=lambda f: abs(f["t"] - (start + end) / 2))] if frames else []
    if not sel:
        return {"score": 0.5, "sharpness": 0, "brightness": 0.5, "shake": 0, "notes": []}
    sharp = float(np.median([f["sharpness"] for f in sel]))
    bright = float(np.mean([f["brightness"] for f in sel]))
    over = float(np.mean([f["over"] for f in sel]))
    under = float(np.mean([f["under"] for f in sel]))
    # shake = high-frequency jitter of the global translation (smooth pans are fine)
    dx = np.array([f["dx"] for f in sel][1:] or [0.0])
    dy = np.array([f["dy"] for f in sel][1:] or [0.0])
    if len(dx) >= 3:
        k = np.ones(3) / 3
        jx = dx - np.convolve(dx, k, mode="same")
        jy = dy - np.convolve(dy, k, mode="same")
        shake = float(np.sqrt(np.mean(jx ** 2 + jy ** 2)))
    else:
        shake = float(np.sqrt(np.mean(dx ** 2 + dy ** 2))) * 0.5
    motion = float(np.mean(np.sqrt(dx ** 2 + dy ** 2)))
    sharp_s = _clip01((math.log10(max(sharp, 1.0)) - 1.3) / (2.6 - 1.3))
    if 0.2 <= bright <= 0.8:
        exp_s = 1.0
    else:
        exp_s = _clip01(1.0 - (min(abs(bright - 0.2), abs(bright - 0.8)) / 0.18))
    exp_s *= 1.0 - _clip01((over + under - 0.15) * 2)
    stab_s = 1.0 - _clip01((shake - 0.006) / 0.03)
    score = round(0.45 * sharp_s + 0.30 * exp_s + 0.25 * stab_s, 3)
    notes = []
    if sharp_s < 0.35:
        notes.append("模糊/失焦")
    if bright < 0.15 or under > 0.4:
        notes.append("太暗")
    if bright > 0.85 or over > 0.3:
        notes.append("过曝")
    if stab_s < 0.4:
        notes.append("抖动")
    return {"score": score, "sharpness": round(sharp, 1), "brightness": round(bright, 3),
            "shake": round(shake, 4), "motion": round(motion, 4), "notes": notes}
