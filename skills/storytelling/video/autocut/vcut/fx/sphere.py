"""Equirectangular (2:1) 360° reprojection with a *general perspective* camera model.

The camera looks along +z (x right, y up). An image-plane point at radius r maps to the off-axis angle θ via

    r = (d+1)·sinθ / (d + cosθ)

d = 0 → rectilinear (normal "flat" view), d = 1 → stereographic (tiny planet / rabbit hole),
d > 1 → towards orthographic (a globe / crystal-ball look). Animating d, fov and pitch together gives the
smooth "planet → normal" transition Insta360 Studio is known for — which ffmpeg's v360 cannot blend
(it switches projection discretely). Everything is vectorised NumPy + cv2.remap.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, replace

import cv2
import numpy as np


@dataclass(frozen=True)
class View:
    yaw: float = 0.0      # degrees, + = turn right
    pitch: float = 0.0    # degrees, + = look up
    roll: float = 0.0     # degrees, + = rotate image clockwise
    fov: float = 100.0    # field of view across the LONGER image side (degrees); may exceed 180 when d ≥ 1
    d: float = 0.0        # projection distance (0 rectilinear … 1 stereographic … >1 globe)

    def rounded(self) -> "View":
        return View(round(self.yaw, 3), round(self.pitch, 3), round(self.roll, 3), round(self.fov, 3), round(self.d, 4))

    def with_(self, **kw) -> "View":
        return replace(self, **kw)


def max_half_fov(d: float) -> float:
    """Largest half-fov (degrees) the projection can show for distance d (minus a safety margin)."""
    if d >= 1.0:
        return 175.0
    return math.degrees(math.acos(-d)) - 6.0


def proj_radius(theta: float, d: float) -> float:
    return (d + 1.0) * math.sin(theta) / (d + math.cos(theta))


def clamp_view(v: View) -> View:
    half = min(v.fov / 2.0, max_half_fov(v.d))
    if v.d > 1.0:  # visible disk limit: angle where dr/dθ = 0 → cosθ = -1/d
        half = min(half, math.degrees(math.acos(-1.0 / v.d)) - 1.0)
    return v.with_(fov=max(5.0, 2 * half))


def rotation(yaw: float, pitch: float, roll: float) -> np.ndarray:
    y, p, r = map(math.radians, (yaw, pitch, roll))
    Ry = np.array([[math.cos(y), 0, math.sin(y)], [0, 1, 0], [-math.sin(y), 0, math.cos(y)]])
    Rx = np.array([[1, 0, 0], [0, math.cos(p), math.sin(p)], [0, -math.sin(p), math.cos(p)]])
    Rz = np.array([[math.cos(r), math.sin(r), 0], [-math.sin(r), math.cos(r), 0], [0, 0, 1]])
    return (Ry @ Rx @ Rz).astype(np.float32)


class Reprojector:
    """Caches the static per-output-pixel grid; builds remap tables per view."""

    def __init__(self, out_w: int, out_h: int, src_w: int, src_h: int):
        self.W, self.H, self.sw, self.sh = out_w, out_h, src_w, src_h
        lw, lh = max(2, out_w // 2), max(2, out_h // 2)
        half = max(out_w, out_h) / 2  # fov always refers to the LONGER side (same feel in 16:9 and 9:16)
        # half-res grid sampled at the same normalized positions as cv2.resize will interpolate from
        u = ((np.arange(lw, dtype=np.float32) + 0.5) * (out_w / lw) - out_w / 2) / half
        v = (out_h / 2 - (np.arange(lh, dtype=np.float32) + 0.5) * (out_h / lh)) / half
        uu, vv = np.meshgrid(u, v)
        self._lo = (np.hypot(uu, vv).astype(np.float32), uu, vv)
        self._base_cache: dict = {}

    def _base(self, pitch: float, roll: float, fov: float, d: float) -> tuple[np.ndarray, np.ndarray, np.ndarray | None]:
        """Maps for yaw = 0 (yaw is a pure longitude shift, added later). Computed at half resolution on the
        direction vectors (continuous, so no seam at ±180°) and upsampled; atan2/asin run at full resolution."""
        key = (pitch, roll, fov, d)
        hit = self._base_cache.get(key)
        if hit is not None:
            return hit
        k = d + 1.0
        rw = proj_radius(math.radians(fov / 2.0), d)
        r0, u, v = self._lo
        r = r0 * np.float32(rw)
        if d == 0.0:
            theta = np.arctan(r)
            valid = None
        else:
            arg = r * np.float32(d) / np.sqrt(np.float32(k * k) + r * r)
            valid = (arg <= 1.0).astype(np.float32)
            theta = np.arctan2(r, np.float32(k)) + np.arcsin(np.clip(arg, -1.0, 1.0))
        s = np.sin(theta) / np.maximum(r0, np.float32(1e-6))
        cx, cy, cz = u * s, v * s, np.cos(theta)
        R = rotation(0.0, pitch, roll)
        full = (self.W, self.H)
        wx = cv2.resize((R[0, 0] * cx + R[0, 1] * cy + R[0, 2] * cz).astype(np.float32), full, interpolation=cv2.INTER_LINEAR)
        wy = cv2.resize((R[1, 0] * cx + R[1, 1] * cy + R[1, 2] * cz).astype(np.float32), full, interpolation=cv2.INTER_LINEAR)
        wz = cv2.resize((R[2, 0] * cx + R[2, 1] * cy + R[2, 2] * cz).astype(np.float32), full, interpolation=cv2.INTER_LINEAR)
        lon = cv2.phase(wz, wx)  # atan2(wx, wz) in [0, 2π)
        lon = np.where(lon > np.float32(math.pi), lon - np.float32(2 * math.pi), lon)
        nrm = np.sqrt(wx * wx + wy * wy + wz * wz)
        lat = np.arcsin(np.clip(wy / np.maximum(nrm, 1e-6), -1.0, 1.0))
        mx = ((lon / np.float32(2 * math.pi) + 0.5) * self.sw - 0.5).astype(np.float32)
        my = ((0.5 - lat / np.float32(math.pi)) * self.sh - 0.5).astype(np.float32)
        mask = None if valid is None else cv2.resize(valid, full, interpolation=cv2.INTER_LINEAR)
        if len(self._base_cache) > 6:
            self._base_cache.pop(next(iter(self._base_cache)))
        self._base_cache[key] = (mx, my, mask)
        return mx, my, mask

    def maps(self, view: View) -> tuple[np.ndarray, np.ndarray, np.ndarray | None]:
        """Returns (map_x, map_y, valid_mask|None) for cv2.remap (BORDER_WRAP handles x outside the frame)."""
        view = clamp_view(view).rounded()
        mx, my, mask = self._base(view.pitch, view.roll, view.fov, view.d)
        shift = np.float32((view.yaw / 360.0) % 1.0 * self.sw)
        return mx + shift, my, mask

    def render(self, equi: np.ndarray, view: View, background: np.ndarray | None = None) -> np.ndarray:
        mx, my, mask = self.maps(view)
        img = cv2.remap(equi, mx, my, interpolation=cv2.INTER_LINEAR, borderMode=cv2.BORDER_WRAP)
        if mask is not None and mask.min() < 1.0:
            bg = background if background is not None else np.zeros_like(img)
            m = cv2.GaussianBlur(mask, (0, 0), 1.2)[..., None]
            img = (img.astype(np.float32) * m + bg.astype(np.float32) * (1 - m)).astype(np.uint8)
        return img

    def render_blur(self, equi: np.ndarray, views: list[View]) -> np.ndarray:
        """Average several sub-frame views → true rotational motion blur (whip pans)."""
        acc = None
        for v in views:
            f = self.render(equi, v).astype(np.float32)
            acc = f if acc is None else acc + f
        return (acc / max(1, len(views))).astype(np.uint8)


def point_to_angles(x: float, y: float, src_w: int, src_h: int) -> tuple[float, float]:
    """Equirect pixel → (yaw, pitch) in degrees."""
    return (x + 0.5) / src_w * 360.0 - 180.0, 90.0 - (y + 0.5) / src_h * 180.0


def view_point_to_angles(px: float, py: float, view: View, W: int, H: int) -> tuple[float, float]:
    """Pixel in a rectilinear (d=0) view → world (yaw, pitch) in degrees."""
    rw = math.tan(math.radians(view.fov / 2))
    half = max(W, H) / 2
    u = (px + 0.5 - W / 2) / half * rw
    v = (H / 2 - py - 0.5) / half * rw
    vec = np.array([u, v, 1.0], np.float32)
    vec /= np.linalg.norm(vec)
    w = rotation(view.yaw, view.pitch, view.roll) @ vec
    return math.degrees(math.atan2(w[0], w[2])), math.degrees(math.asin(max(-1.0, min(1.0, float(w[1])))))


def is_equirect(width: int, height: int) -> bool:
    return bool(width and height) and abs(width / height - 2.0) < 0.01 and width >= 1280
