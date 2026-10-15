"""Custom transitions rendered frame-by-frame from the tail of clip A and the head of clip B.

whip_*        directional whip-pan: both shots slide with heavy motion blur peaking mid-way
spin/_ccw     roll transition: A spins out with zoom + rotational blur, B spins in
zoom_through  3D-ish push through A (radial blur, scale ×3) into B arriving from depth
glitch        RGB split / block displacement ramps up on A, cuts to B mid-way, ramps down
flash         exposure blow-out to white and back (non-linear), cut in the white
light_leak    cross-dissolve under a strong drifting light leak
The overlap (d seconds) equals the xfade overlap, so timeline maths is identical to ffmpeg transitions.
"""
from __future__ import annotations

import math
import os
import subprocess
from pathlib import Path

import cv2
import numpy as np

from ..media import FFmpegError, ffmpeg_bin, video_encode_args
from .ease import ease
from .effects import Glitch, LightLeak

_NOWIN = {"creationflags": 0x08000000} if os.name == "nt" else {}


def _read(path: Path, start: float, n: int, W: int, H: int, fps: int) -> list[np.ndarray]:
    cmd = [ffmpeg_bin(), "-hide_banner", "-nostdin", "-v", "error", "-ss", f"{max(0.0, start):.3f}", "-i", str(path),
           "-frames:v", str(n), "-vf", f"fps={fps},scale={W}:{H},format=bgr24", "-f", "rawvideo", "pipe:1"]
    raw = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False, **_NOWIN).stdout
    sz = W * H * 3
    frames = [np.frombuffer(raw[k * sz:(k + 1) * sz], np.uint8).reshape(H, W, 3) for k in range(len(raw) // sz)]
    if not frames:
        frames = [np.zeros((H, W, 3), np.uint8)]
    while len(frames) < n:
        frames.append(frames[-1])
    return frames[:n]


def _dir_blur(img: np.ndarray, length: int, horizontal: bool) -> np.ndarray:
    if length < 3:
        return img
    k = (length | 1, 1) if horizontal else (1, length | 1)
    return cv2.blur(img, k)


def _shift(img: np.ndarray, dx: int, dy: int) -> np.ndarray:
    M = np.float32([[1, 0, dx], [0, 1, dy]])
    return cv2.warpAffine(img, M, (img.shape[1], img.shape[0]), borderMode=cv2.BORDER_REFLECT101)


def _rot_zoom(img: np.ndarray, ang: float, z: float) -> np.ndarray:
    H, W = img.shape[:2]
    M = cv2.getRotationMatrix2D((W / 2, H / 2), ang, z)
    return cv2.warpAffine(img, M, (W, H), borderMode=cv2.BORDER_REFLECT101)


def _avg(frames: list[np.ndarray]) -> np.ndarray:
    acc = frames[0].astype(np.float32)
    for f in frames[1:]:
        acc += f
    return (acc / len(frames)).astype(np.uint8)


def whip(a: np.ndarray, b: np.ndarray, x: float, direction: str) -> np.ndarray:
    H, W = a.shape[:2]
    horiz = direction in ("left", "right")
    L = W if horiz else H
    sgn = -1 if direction in ("left", "up") else 1
    # one continuous pan: position p goes 0 → 1 (A fully out, B fully in) with in_out_expo-like speed
    p = ease("in_out_cubic", x)
    vel = math.sin(math.pi * x)  # blur strength ∝ speed
    off = int(sgn * p * L)
    fa = _shift(a, off if horiz else 0, 0 if horiz else off)
    fb = _shift(b, (off - sgn * L) if horiz else 0, 0 if horiz else (off - sgn * L))
    # stitch: A occupies the leading part, B the trailing part
    out = fa.copy()
    if horiz:
        edge = off if sgn > 0 else W + off
        if sgn > 0:
            out[:, :max(0, edge)] = fb[:, :max(0, edge)]
        else:
            out[:, max(0, edge):] = fb[:, max(0, edge):]
    else:
        edge = off if sgn > 0 else H + off
        if sgn > 0:
            out[:max(0, edge)] = fb[:max(0, edge)]
        else:
            out[max(0, edge):] = fb[max(0, edge):]
    out = _dir_blur(out, int(vel * L * 0.18), horiz)
    lift = 0.12 * vel
    return cv2.addWeighted(out, 1 - lift, np.full_like(out, 255), lift, 0)


def spin(a: np.ndarray, b: np.ndarray, x: float, ccw: bool) -> np.ndarray:
    sgn = 1 if ccw else -1
    if x < 0.5:
        u = ease("in_cubic", x / 0.5)
        src, ang, z, vel = a, sgn * 180 * u, 1 + 0.6 * u, u
    else:
        u = ease("out_cubic", (x - 0.5) / 0.5)
        src, ang, z, vel = b, sgn * (-180 + 180 * u), 1.6 - 0.6 * u, 1 - u
    n = 1 + int(vel * 6)
    frames = [_rot_zoom(src, ang - sgn * 14 * vel * k / max(1, n - 1), z) for k in range(n)]
    return _avg(frames)


def zoom_through(a: np.ndarray, b: np.ndarray, x: float) -> np.ndarray:
    """Classic 'zoom in' transition: A rushes into its centre with radial blur, B arrives still enlarged
    and settles to 100% (keeps the forward momentum, never shows borders)."""
    if x < 0.5:
        u = ease("in_cubic", x / 0.5)
        src, z, vel = a, 1 + 2.2 * u, u
    else:
        u = ease("out_cubic", (x - 0.5) / 0.5)
        src, z, vel = b, 2.0 - 1.0 * u, 1 - u
    n = 1 + int(vel * 7)
    frames = [_rot_zoom(src, 0, z * (1 + 0.05 * vel * k)) for k in range(n)]
    out = _avg(frames)
    flash = 0.35 * math.exp(-((x - 0.5) / 0.08) ** 2)
    return cv2.addWeighted(out, 1 - flash, np.full_like(out, 255), flash, 0)


class Transitioner:
    def __init__(self, kind: str, W: int, H: int, fps: int, seed: int = 0):
        self.kind, self.W, self.H, self.fps = kind, W, H, fps
        self.glitch = Glitch(W, H, fps, 1.0, {"on": "always"}, seed)
        self.leak = LightLeak(W, H, fps, 1.0, {"palette": "warm"}, seed)

    def frame(self, a: np.ndarray, b: np.ndarray, x: float, t: float) -> np.ndarray:
        k = self.kind
        if k.startswith("whip_"):
            return whip(a, b, x, k.split("_", 1)[1])
        if k in ("spin", "spin_ccw"):
            return spin(a, b, x, k == "spin_ccw")
        if k == "zoom_through":
            return zoom_through(a, b, x)
        if k == "glitch":
            src = a if x < 0.5 else b
            g = math.sin(math.pi * x)
            return self.glitch(src, t, 0.25 + 0.75 * g)
        if k == "flash":
            w = math.exp(-((x - 0.5) / 0.2) ** 2)
            src = a if x < 0.5 else b
            return cv2.addWeighted(src, 1 - w, np.full_like(src, 255), w, 0)
        if k == "light_leak":
            mix = cv2.addWeighted(a, 1 - ease("in_out_sine", x), b, ease("in_out_sine", x), 0)
            return self.leak(mix, t * 2.0, math.sin(math.pi * x) ** 0.7)
        return cv2.addWeighted(a, 1 - x, b, x, 0)


def render_transition(kind: str, a_path: Path, a_dur: float, b_path: Path, d: float, out: Path, W: int, H: int, fps: int,
                      *, encoder: str, quick: bool, seed: int = 0) -> Path:
    n = max(1, int(round(d * fps)))
    fa = _read(a_path, a_dur - n / fps, n, W, H, fps)
    fb = _read(b_path, 0.0, n, W, H, fps)
    tr = Transitioner(kind, W, H, fps, seed)
    venc = (video_encode_args(encoder, {"crf": 16, "nvenc_cq": 17}, fast=True) if not quick
            else video_encode_args("libx264" if "nvenc" not in encoder else encoder, {"crf": 23}, fast=True))
    cmd = [ffmpeg_bin(), "-hide_banner", "-nostdin", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "bgr24",
           "-s", f"{W}x{H}", "-r", str(fps), "-i", "pipe:0", "-vf", "setsar=1,format=yuv420p", *venc,
           "-r", str(fps), "-video_track_timescale", str(fps * 1000), str(out)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE, **_NOWIN)
    for k in range(n):
        x = (k + 0.5) / n
        proc.stdin.write(np.ascontiguousarray(tr.frame(fa[k], fb[k], x, k / fps)).tobytes())  # type: ignore[union-attr]
    proc.stdin.close()  # type: ignore[union-attr]
    err = proc.stderr.read().decode("utf-8", "replace")  # type: ignore[union-attr]
    if proc.wait() != 0:
        raise FFmpegError(f"转场 {kind} 渲染失败：{err[-800:]}")
    return out
