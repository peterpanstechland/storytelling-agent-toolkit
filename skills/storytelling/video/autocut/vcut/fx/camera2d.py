"""Camera moves on flat footage: an eased virtual crop window (centre, zoom, roll) inside a base frame.

The base frame covers the output (it may be wider/taller, e.g. a 16:9 source for a 9:16 output), so pans and
subject framing have room to move. cv2.warpAffine gives sub-pixel smooth motion (no zoompan jitter).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from .ease import Track, ease, lerp


@dataclass
class Cam:
    cx: float = 0.5      # window centre in base (0..1)
    cy: float = 0.5
    zoom: float = 1.0    # 1 = window just covers the output
    angle: float = 0.0   # degrees (+ = clockwise)


def _noise(t: float, seed: int, freqs=(0.9, 1.7, 3.1)) -> float:
    rng = np.random.default_rng(seed)
    ph = rng.uniform(0, 2 * math.pi, len(freqs))
    amp = np.array([1.0, 0.55, 0.3])[: len(freqs)]
    return float(sum(a * math.sin(2 * math.pi * f * t + p) for a, f, p in zip(amp, freqs, ph)) / amp.sum())


def pulse_env(t: float, times: list[float], decay: float = 0.18, attack: float = 0.03) -> float:
    """Sum of fast-attack / exponential-decay pulses at the given times (clipped to 1)."""
    v = 0.0
    for b in times:
        dt = t - b
        if -attack <= dt < decay * 5:
            v += (dt + attack) / attack if dt < 0 else math.exp(-dt / decay)
    return min(1.0, v)


class Camera2D:
    def __init__(self, move_type: str, params: dict | None, dur: float, out_w: int, out_h: int, base_w: int, base_h: int,
                 *, focus_track: list[list[float]] | None = None, focus_x: float = 0.5, beats: list[float] | None = None,
                 shake: float = 0.0, shake_beats: bool = False, punch: float = 0.0, seed: int = 0):
        self.type = move_type or "none"
        self.p = dict(params or {})
        self.dur = max(0.05, dur)
        self.W, self.H, self.bw, self.bh = out_w, out_h, base_w, base_h
        self.sc = max(out_w / base_w, out_h / base_h)  # base px → output px at zoom 1
        ft = [k for k in (focus_track or []) if len(k) >= 3]
        self._fx = Track([(k[0], k[1]) for k in ft], "linear") if ft else None
        self._fy = Track([(k[0], k[2]) for k in ft], "linear") if ft else None
        self.focus_x = focus_x
        self.beats = sorted(beats or [])
        self.shake = float(self.p.get("amount", 0.35)) if self.type == "shake" else shake
        self.shake_beats = shake_beats
        self.punch = float(self.p.get("amount", 0.14)) if self.type == "punch" else punch
        self.seed = seed

    def focus(self, t: float) -> tuple[float, float]:
        if self._fx is not None:
            return self._fx(t), self._fy(t)  # type: ignore[misc]
        return self.focus_x, 0.5

    def state(self, t: float) -> Cam:
        x = min(1.0, max(0.0, t / self.dur))
        fx, fy = self.focus(t)
        cam = Cam(fx, fy, 1.0, 0.0)
        m, amt = self.type, float(self.p.get("amount", 0.0) or 0.0)
        ez = self.p.get("ease", "in_out_cubic")
        if m == "push_in":
            cam.zoom = 1.0 + (amt or 0.14) * ease(ez, x)
        elif m == "pull_out":
            cam.zoom = 1.0 + (amt or 0.14) * (1.0 - ease(ez, x))
        elif m in ("pan", "tilt"):
            d = -1.0 if self.p.get("direction") in ("left", "up") else 1.0
            e = ease(self.p.get("ease", "in_out_sine"), x)
            z = 1.0 + amt
            for _ in range(2):
                win = (self.W / (self.sc * z) / self.bw) if m == "pan" else (self.H / (self.sc * z) / self.bh)
                rng = (1.0 - win) / 2 * 0.92
                if rng >= 0.06:
                    break
                z = 1.0 + max(amt, 0.2)
            cam.zoom = z
            if m == "pan":
                cam.cx = 0.5 + d * rng * lerp(-1.0, 1.0, e)
            else:
                cam.cy = 0.5 + d * rng * lerp(-1.0, 1.0, e)
        elif m == "roll":
            deg = float(self.p.get("degrees", 6.0))
            cam.angle = deg * ease("in_out_sine", x)
            th = math.radians(abs(cam.angle))
            ar = max(self.W / self.H, self.H / self.W)
            cam.zoom = max(1.03, math.cos(th) + ar * math.sin(th) + 0.01)  # cover the rotated corners
        elif m == "subject":
            cam.zoom = 1.0 + (amt or 0.06) * ease("in_out_sine", x)
        # beat punch-in (卡点放大)
        if self.punch > 0 and self.beats:
            pe = pulse_env(t, self.beats, decay=float(self.p.get("decay", 0.16)))
            cam.zoom *= 1.0 + self.punch * pe
            if self.p.get("punch_roll", True):
                k = sum(1 for b in self.beats if b <= t)
                cam.angle += (1.2 if k % 2 else -1.2) * pe * min(1.0, self.punch * 6)
        # handheld shake
        if self.shake > 0:
            a = self.shake * (pulse_env(t, self.beats, decay=0.25) if self.shake_beats and self.beats else 1.0)
            jitter = 1.0 if not self.shake_beats else 3.0
            cam.cx += 0.012 * a * jitter * _noise(t, self.seed + 1, (1.1, 2.3, 4.7))
            cam.cy += 0.010 * a * jitter * _noise(t, self.seed + 2, (0.8, 2.9, 5.3))
            cam.angle += 0.7 * a * jitter * _noise(t, self.seed + 3, (0.6, 1.9, 3.7))
            cam.zoom *= 1.0 + 0.035 * a * jitter
        return self.clamp(cam)

    def clamp(self, cam: Cam) -> Cam:
        th = math.radians(abs(cam.angle))
        ar = self.W / self.H
        zmin = abs(math.cos(th)) + abs(math.sin(th)) * max(ar, 1 / ar)  # cover the rotated corners
        cam.zoom = max(cam.zoom, zmin, 1.0)
        ww = self.W / (self.sc * cam.zoom) / self.bw  # window size in base-normalized units
        wh = self.H / (self.sc * cam.zoom) / self.bh
        cam.cx = min(1 - ww / 2, max(ww / 2, cam.cx))
        cam.cy = min(1 - wh / 2, max(wh / 2, cam.cy))
        return cam

    def matrix(self, cam: Cam) -> np.ndarray:
        """2×3 inverse map (output px → base px) for cv2.warpAffine(..., WARP_INVERSE_MAP)."""
        s = 1.0 / (self.sc * cam.zoom)
        th = math.radians(cam.angle)
        a, b = math.cos(th) * s, math.sin(th) * s
        Cx, Cy = cam.cx * self.bw, cam.cy * self.bh
        Ox, Oy = self.W / 2, self.H / 2
        return np.array([[a, -b, Cx - a * Ox + b * Oy], [b, a, Cy - b * Ox - a * Oy]], np.float32)

    def displacement_px(self, c0: Cam, c1: Cam) -> float:
        """Approximate max on-screen pixel motion between two states (drives motion-blur sub-sampling)."""
        dx = (c1.cx - c0.cx) * self.bw * self.sc * c1.zoom
        dy = (c1.cy - c0.cy) * self.bh * self.sc * c1.zoom
        dz = abs(c1.zoom / c0.zoom - 1.0) * max(self.W, self.H) / 2
        da = math.radians(abs(c1.angle - c0.angle)) * max(self.W, self.H) / 2
        return math.hypot(dx, dy) + dz + da
