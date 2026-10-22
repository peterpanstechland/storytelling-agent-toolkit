"""X5 360° auto camera moves → a View (yaw/pitch/roll/fov/d) per output time.

All moves are eased (never linear) and, when a subject heading track exists, are anchored on the subject.
Motion blur for fast moves (whip, orbit) is produced by the engine by sub-sampling views over the shutter.
"""
from __future__ import annotations

import math

from .ease import Track, ease, lerp
from .sphere import View

DEFAULT_FOV = {"landscape": 100.0, "portrait": 92.0}


class Shot360:
    def __init__(self, move_type: str, params: dict | None, dur: float, *, portrait: bool = False,
                 yaw_track: list[list[float]] | None = None):
        self.type = move_type or "follow"
        self.p = dict(params or {})
        self.dur = max(0.05, dur)
        self.portrait = portrait
        self.fov = float(self.p.get("fov", DEFAULT_FOV["portrait" if portrait else "landscape"]))
        yt = [k for k in (yaw_track or []) if len(k) >= 3]
        self._yaw = Track([(k[0], k[1]) for k in yt], "linear") if yt else None
        self._pitch = Track([(k[0], k[2]) for k in yt], "linear") if yt else None
        self.base_yaw = float(self.p.get("yaw", yt[0][1] if yt else 0.0))
        self.base_pitch = float(self.p.get("pitch", -2.0))

    # subject heading (tracked) or fixed
    def heading(self, t: float) -> tuple[float, float]:
        if self._yaw is not None and self.type in ("follow", "hero", "fixed360", "planet_intro", "whip360", "crystal_ball"):
            off = float(self.p.get("yaw_offset", 0.0))
            pitch = max(-35.0, min(25.0, self._pitch(t) + float(self.p.get("pitch_offset", 0.0))))  # type: ignore[misc]
            return self._yaw(t) + off, pitch  # type: ignore[misc]
        return self.base_yaw, self.base_pitch

    @property
    def special(self) -> str | None:
        return "crystal_ball" if self.type == "crystal_ball" else None

    def view(self, t: float) -> View:
        T, x = self.dur, min(1.0, max(0.0, t / self.dur))
        yaw, pitch = self.heading(t)
        m = self.type
        if m == "orbit":
            turns = float(self.p.get("turns", 1.0 if T >= 4 else 0.5))
            direction = -1.0 if self.p.get("direction") == "left" else 1.0
            return View(self.base_yaw + direction * 360.0 * turns * ease("in_out_sine", x), float(self.p.get("pitch", -6.0)),
                        0.0, self.fov + 6.0 * math.sin(math.pi * x))
        if m == "hero":
            e = ease("in_out_cubic", x)
            return View(yaw + lerp(-38.0, 14.0, e), lerp(-32.0, -10.0, e), lerp(-5.0, 0.0, e),
                        lerp(self.fov + 30.0, self.fov - 10.0, e), lerp(0.35, 0.04, e))
        if m == "whip360":
            at = float(self.p.get("at", 0.5)) * T
            w = float(self.p.get("whip", 0.34))
            delta = float(self.p.get("delta", 150.0))
            k = ease("in_out_expo", (t - (at - w / 2)) / w)
            punch = math.exp(-((t - at) / (w * 0.6)) ** 2)
            return View(yaw + delta * k, pitch, 0.0, self.fov + 14.0 * punch)
        if m == "tiny_planet":
            spin = float(self.p.get("spin", 24.0))  # degrees per second
            return View(self.base_yaw + spin * t, -90.0, 0.0, lerp(300.0, 320.0, ease("in_out_sine", x)), 1.0)
        if m == "rabbit_hole":
            spin = float(self.p.get("spin", -30.0))
            return View(self.base_yaw + spin * t, 90.0, 0.0, lerp(250.0, 270.0, ease("in_out_sine", x)), 1.0)
        if m == "planet_intro":
            Tt = min(float(self.p.get("transition", 2.6)), 0.8 * T)
            if t < Tt:
                u = t / Tt
                e = ease("in_out_cubic", u)
                ed = ease("in_quad", u) if u < 1 else 1.0  # keep the stereographic look a little longer
                return View(yaw - lerp(160.0, 0.0, e), lerp(-90.0, pitch, e), 0.0,
                            lerp(305.0, self.fov, e), lerp(1.0, 0.0, ed))
            u = (t - Tt) / max(1e-3, T - Tt)
            return View(yaw + 6.0 * ease("in_out_sine", u), pitch, 0.0, self.fov - 6.0 * ease("in_out_sine", u))
        if m == "fixed360":
            return View(yaw, pitch, 0.0, self.fov)
        # follow (default): subject-locked with a slow eased push
        return View(yaw, pitch, 0.0, self.fov + 6.0 - 12.0 * ease("in_out_sine", x))

    # crystal ball: tiny planet inside a glass ball over a blurred normal view
    def ball(self, t: float) -> tuple[View, View, float]:
        yaw, pitch = self.heading(t)
        x = t / self.dur
        bg = View(yaw + 10.0 * x, pitch, 0.0, self.fov + 10.0)
        inner = View(self.base_yaw + float(self.p.get("spin", 35.0)) * t, -90.0, 0.0, 250.0, 1.0)
        pop = ease("out_back", min(1.0, t / 0.6))
        return bg, inner, pop
