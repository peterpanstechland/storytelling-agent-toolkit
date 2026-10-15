"""Easing curves and keyframe tracks (all times in seconds, values float)."""
from __future__ import annotations

import math
from bisect import bisect_right
from typing import Callable, Sequence

import numpy as np


def _clamp01(x: float) -> float:
    return 0.0 if x <= 0 else 1.0 if x >= 1 else x


EASINGS: dict[str, Callable[[float], float]] = {
    "linear": lambda x: x,
    "in_sine": lambda x: 1 - math.cos(x * math.pi / 2),
    "out_sine": lambda x: math.sin(x * math.pi / 2),
    "in_out_sine": lambda x: -(math.cos(math.pi * x) - 1) / 2,
    "in_quad": lambda x: x * x,
    "out_quad": lambda x: 1 - (1 - x) ** 2,
    "in_out_quad": lambda x: 2 * x * x if x < 0.5 else 1 - (-2 * x + 2) ** 2 / 2,
    "in_cubic": lambda x: x ** 3,
    "out_cubic": lambda x: 1 - (1 - x) ** 3,
    "in_out_cubic": lambda x: 4 * x ** 3 if x < 0.5 else 1 - (-2 * x + 2) ** 3 / 2,
    "in_expo": lambda x: 0.0 if x == 0 else 2 ** (10 * x - 10),
    "out_expo": lambda x: 1.0 if x == 1 else 1 - 2 ** (-10 * x),
    "in_out_expo": lambda x: (0.0 if x == 0 else 1.0 if x == 1 else
                              2 ** (20 * x - 10) / 2 if x < 0.5 else (2 - 2 ** (-20 * x + 10)) / 2),
    "out_back": lambda x: 1 + 2.70158 * (x - 1) ** 3 + 1.70158 * (x - 1) ** 2,
    "in_back": lambda x: 2.70158 * x ** 3 - 1.70158 * x * x,
    "out_elastic": lambda x: (0.0 if x == 0 else 1.0 if x == 1 else
                              2 ** (-10 * x) * math.sin((x * 10 - 0.75) * (2 * math.pi / 3)) + 1),
    "smoothstep": lambda x: x * x * (3 - 2 * x),
}


def ease(name: str, x: float) -> float:
    return EASINGS.get(name, EASINGS["in_out_sine"])(_clamp01(x))


def lerp(a: float, b: float, x: float) -> float:
    return a + (b - a) * x


def lerp_angle(a: float, b: float, x: float) -> float:
    """Shortest-path angle interpolation in degrees (result unwrapped near a)."""
    d = (b - a + 180.0) % 360.0 - 180.0
    return a + d * x


class Track:
    """Piecewise keyframe track. keys: [(t, value, ease_into_this_key)]."""

    def __init__(self, keys: Sequence[tuple[float, float] | tuple[float, float, str]], default_ease: str = "in_out_sine"):
        ks = sorted(((k[0], k[1], k[2] if len(k) > 2 else default_ease) for k in keys), key=lambda k: k[0])
        self.t = [k[0] for k in ks]
        self.v = [k[1] for k in ks]
        self.e = [k[2] for k in ks]

    def __call__(self, t: float) -> float:
        if not self.t:
            return 0.0
        if t <= self.t[0]:
            return self.v[0]
        if t >= self.t[-1]:
            return self.v[-1]
        i = bisect_right(self.t, t)
        t0, t1 = self.t[i - 1], self.t[i]
        x = (t - t0) / (t1 - t0) if t1 > t0 else 1.0
        return lerp(self.v[i - 1], self.v[i], ease(self.e[i], x))

    def sample(self, times: Sequence[float]) -> list[float]:
        return [self(t) for t in times]


def smooth_series(values: Sequence[float], times: Sequence[float], sigma_s: float = 0.6,
                  max_rate: float | None = None, circular: bool = False) -> np.ndarray:
    """Gaussian smoothing over (possibly unevenly spaced) samples + optional slew-rate limit (units/s).
    circular=True treats values as degrees and unwraps first."""
    v = np.asarray(values, dtype=np.float64)
    t = np.asarray(times, dtype=np.float64)
    if len(v) == 0:
        return v
    if circular:
        v = np.degrees(np.unwrap(np.radians(v)))
    out = np.empty_like(v)
    for i, ti in enumerate(t):
        w = np.exp(-0.5 * ((t - ti) / max(sigma_s, 1e-3)) ** 2)
        out[i] = float((w * v).sum() / w.sum())
    if max_rate:
        for i in range(1, len(out)):
            dt = max(t[i] - t[i - 1], 1e-6)
            out[i] = out[i - 1] + float(np.clip(out[i] - out[i - 1], -max_rate * dt, max_rate * dt))
    return out


def ease_time_remap(duration_out: float, src_duration: float, profile: Sequence[tuple[float, float]],
                    fps: int) -> np.ndarray:
    """Map each output frame to a source time for a smooth speed ramp.

    profile: [(x_out in 0..1, speed)] control points; speed is interpolated with smoothstep between points and
    then globally scaled so that the integral covers exactly src_duration over duration_out.
    """
    n = max(1, int(round(duration_out * fps)))
    xs = (np.arange(n) + 0.5) / n
    px = [p[0] for p in profile]
    ps = [p[1] for p in profile]
    sp = np.empty(n)
    for i, x in enumerate(xs):
        j = max(1, min(len(px) - 1, bisect_right(px, x)))
        x0, x1 = px[j - 1], px[j]
        u = 0.0 if x1 <= x0 else min(1.0, max(0.0, (x - x0) / (x1 - x0)))
        u = u * u * (3 - 2 * u)
        sp[i] = ps[j - 1] + (ps[j] - ps[j - 1]) * u
    cum = np.concatenate([[0.0], np.cumsum(sp)])[:-1] + sp / 2
    total = cum[-1] + sp[-1] / 2
    return cum / total * src_duration
