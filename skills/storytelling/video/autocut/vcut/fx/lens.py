"""lens_look — a NumPy/OpenCV port of the "camera filming an LED screen" lens shader from mrsarac/ff-tracking
(MIT, https://github.com/mrsarac/ff-tracking, lens/shaders/lens.sksl). Credit: see NOTICE.md.

Stage order follows the shader: tear → perspective plane (virtual camera tilt/zoom/aim) → depth of field
(bokeh-weighted, driven by the tracked target) → radial chromatic aberration + palette mapping → bloom →
equal-area RGB LED grid → exposure kick, vignette, flicker, grain.

Differences from the original, on purpose (it was written for a generated flat screen, this runs on footage):
  * DoF: the shader's circle of confusion is |1 - zf/z| from the tilted plane's depth. On flat footage that is
    zero, so we add a radial term (distance from the tracked target) — `dof_mode: plane|radial|both` (default both).
    The blur is a bokeh-weighted blend of a few Gaussian levels instead of 36 spiral taps per pixel.
  * Perspective: same ray/plane maths, evaluated on a coarse grid and resized, then cv2.remap. `fit: cover`
    (default for footage) raises the zoom until the tilted plane fills the frame; `fit: black` keeps the shader's
    black outside (terminal card).
  * Palettes are applied through 256-entry LUTs (luma → 5-stop gradient per channel), `palette_mix` blends back
    the original colour (footage usually wants 0.5–0.9, the shader is 1.0). No red pass-through unless keep_red.
Typical cost: 25–60 ms per 1080p frame on a laptop CPU (single process), most of it the DoF blur levels.
"""
from __future__ import annotations

import math

import cv2
import numpy as np

from .effects import Effect

FOCAL = 1.7
LH = 1080.0
CELL = 3.0

# 5-stop palettes (BGR is derived below). Colours from ff-tracking hud/src/lib.rs (MIT).
_HEX = {
    "paper": (0xecebe6, 0xc9c8c2, 0x77766f, 0x2a2a28, 0x0c0c0c),
    "thermal": (0x050310, 0x3a0b6b, 0xb3306a, 0xf6862a, 0xfcf6b4),
    "mono": (0x050506, 0x2b2c2e, 0x8a8c90, 0xd9dadc, 0xffffff),
    "phosphor": (0x010604, 0x05361b, 0x13a85a, 0x7dffb4, 0xeafff3),
    "amber": (0x070300, 0x3d1a02, 0xb35a09, 0xffae3d, 0xfff3d6),
    "navy": (0x071451, 0x0d2a8c, 0x4a63d6, 0xb8c4ff, 0xf4f6ff),
    "neon": (0x000502, 0x003d1e, 0x00c46a, 0x5dffae, 0xf0fff6),
}
PALETTES = {k: [((h >> 16) & 255, (h >> 8) & 255, h & 255) for h in v] for k, v in _HEX.items()}
RED_BGR = (26, 33, 255)  # shader: float3(1.0, 0.13, 0.10)

CAM_PRESETS = {  # tilt degrees (x, y, roll), zoom (start, end), pan drift in logical px
    "none": {"tilt": (0, 0, 0), "zoom": (1.0, 1.0), "pan": (0, 0)},
    "subtle": {"tilt": (1.5, -3.0, -0.8), "zoom": (1.0, 1.06), "pan": (-12, 0)},
    "medium": {"tilt": (3.0, -9.0, 1.5), "zoom": (1.08, 1.22), "pan": (-30, 6)},
    "dramatic": {"tilt": (10.0, 35.0, -3.0), "zoom": (1.5, 1.9), "pan": (10, 0)},  # ff-tracking-like scene 0
}


def palette_lut(name: str) -> np.ndarray | None:
    """uint8 (256, 3) BGR lookup table, or None."""
    st = PALETTES.get(name)
    if st is None:
        return None
    xs = np.linspace(0, 1, 5)
    q = np.linspace(0, 1, 256)
    rgb = np.stack([np.interp(q, xs, [s[c] for s in st]) for c in range(3)], axis=1)
    return np.ascontiguousarray(rgb[:, ::-1]).astype(np.uint8)


def _rot(rx: float, ry: float, rz: float) -> np.ndarray:
    cx, sx, cy, sy, cz, sz = math.cos(rx), math.sin(rx), math.cos(ry), math.sin(ry), math.cos(rz), math.sin(rz)
    Rx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
    Ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    Rz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])
    return Rz @ Ry @ Rx


def smoothstep(a: float, b: float, x):
    t = np.clip((x - a) / (b - a), 0, 1)
    return t * t * (3 - 2 * t)


class LensCam:
    """Virtual camera facing a flat plane (the frame). Logical space is LH=1080 tall, LW=1080*W/H wide."""

    def __init__(self, W: int, H: int, params: dict | None = None):
        p = dict(params or {})
        self.W, self.H = W, H
        self.LW = LH * W / H
        preset = p.get("camera") or p.get("cam")
        base = dict(CAM_PRESETS.get(preset if isinstance(preset, str) else "none", CAM_PRESETS["none"]))
        if isinstance(preset, dict):
            base.update(preset)
        for k in ("tilt", "zoom", "pan"):
            if k in p:
                base[k] = p[k]
        tilt = list(base["tilt"]) + [0, 0, 0]
        self.tilt0 = [math.radians(float(v)) for v in tilt[:3]]
        t1 = p.get("tilt_to")
        self.tilt1 = [math.radians(float(v)) for v in (list(t1) + [0, 0, 0])[:3]] if t1 else self.tilt0
        z = base["zoom"]
        self.zoom0, self.zoom1 = (float(z[0]), float(z[1])) if isinstance(z, (list, tuple)) else (float(z), float(z))
        self.pan = tuple(float(v) for v in base.get("pan", (0, 0)))
        aim = p.get("aim")
        self.aim = (float(aim[0]) * self.LW, float(aim[1]) * LH) if aim else (self.LW / 2, LH / 2)
        self.fit = str(p.get("fit", "cover"))
        self.sway = float(p.get("sway", 0.0))
        self.seed = int(p.get("seed", 0))

    @property
    def static_identity(self) -> bool:
        return (max(abs(v) for v in self.tilt0 + self.tilt1) < 1e-6 and self.zoom0 == self.zoom1 == 1.0
                and self.pan == (0, 0) and self.sway == 0 and self.aim == (self.LW / 2, LH / 2))

    def state(self, x: float):
        """x in 0..1 over the shot → (rotation vec, zoom, aim)."""
        x = min(1.0, max(0.0, x))
        e = x * x * (3 - 2 * x)
        rot = [a + (b - a) * e for a, b in zip(self.tilt0, self.tilt1)]
        zoom = self.zoom0 + (self.zoom1 - self.zoom0) * e
        aim = (self.aim[0] + self.pan[0] * x, self.aim[1] + self.pan[1] * x)
        return rot, zoom, aim

    def with_sway(self, rot, t):
        if not self.sway:
            return rot
        from .camera2d import _noise
        a = math.radians(self.sway)
        return [rot[0] + a * _noise(t, self.seed + 11, (0.9, 2.3)), rot[1] + a * _noise(t, self.seed + 12, (0.7, 1.9)),
                rot[2] + 0.4 * a * _noise(t, self.seed + 13, (1.1, 2.7))]

    def _grid(self, rot, zoom, aim, gw, gh, px, py):
        """Plane hit for output pixel coords (px, py) (full-res units). → base(x,y) logical, z, valid."""
        s_x = (px - 0.5 * self.W) / self.H
        s_y = (py - 0.5 * self.H) / self.H
        R = _rot(*rot)
        eu, ev, n = R[:, 0], R[:, 1], R[:, 2]
        dn = s_x * n[0] + s_y * n[1] + FOCAL * n[2]
        valid = dn > 1e-4
        dn = np.where(valid, dn, 1.0)
        t = n[2] / dn
        hx, hy, hz = s_x * t, s_y * t, FOCAL * t
        hz1 = hz - 1.0
        lx = hx * eu[0] + hy * eu[1] + hz1 * eu[2]
        ly = hx * ev[0] + hy * ev[1] + hz1 * ev[2]
        K = FOCAL * LH / zoom
        return aim[0] + lx * K, aim[1] + ly * K, hz, valid, (eu, ev, K)

    def _covers(self, rot, zoom, aim) -> bool:
        xs = np.array([0, 0.5, 1, 0, 1, 0, 0.5, 1]) * self.W
        ys = np.array([0, 0, 0, 0.5, 0.5, 1, 1, 1]) * self.H
        bx, by, _, valid, _ = self._grid(rot, zoom, aim, 0, 0, xs, ys)
        return bool(valid.all() and bx.min() >= 0 and by.min() >= 0 and bx.max() <= self.LW and by.max() <= LH)

    def solve(self, x: float, t: float = 0.0):
        rot, zoom, aim = self.state(x)
        rot = self.with_sway(rot, t)
        if self.fit == "cover":
            for _ in range(24):
                if self._covers(rot, zoom, aim):
                    break
                zoom *= 1.04
                # keep the view inside by pulling the aim toward the centre
                aim = (aim[0] + (self.LW / 2 - aim[0]) * 0.25, aim[1] + (LH / 2 - aim[1]) * 0.25)
        return rot, zoom, aim

    def maps(self, rot, zoom, aim, ds: int = 4):
        gw, gh = max(2, self.W // ds), max(2, self.H // ds)
        px = (np.arange(gw, dtype=np.float32) + 0.5) * (self.W / gw)
        py = (np.arange(gh, dtype=np.float32) + 0.5) * (self.H / gh)
        PX, PY = np.meshgrid(px, py)
        bx, by, z, valid, extra = self._grid(rot, zoom, aim, gw, gh, PX, PY)
        bx = np.where(valid, bx, -1e4).astype(np.float32)
        by = np.where(valid, by, -1e4).astype(np.float32)
        return bx, by, z.astype(np.float32), extra

    def project(self, pts: np.ndarray, rot, zoom, aim) -> np.ndarray:
        """Source-frame pixel coordinates (N,2) → output pixel coordinates after the camera."""
        pts = np.asarray(pts, np.float64)
        bx = pts[:, 0] / self.W * self.LW
        by = pts[:, 1] / self.H * LH
        R = _rot(*rot)
        eu, ev = R[:, 0], R[:, 1]
        K = FOCAL * LH / zoom
        lx, ly = (bx - aim[0]) / K, (by - aim[1]) / K
        hit = np.array([0, 0, 1.0])[None] + lx[:, None] * eu[None] + ly[:, None] * ev[None]
        hz = np.maximum(hit[:, 2], 1e-3)
        sx, sy = hit[:, 0] * FOCAL / hz, hit[:, 1] * FOCAL / hz
        return np.stack([sx * self.H + 0.5 * self.W, sy * self.H + 0.5 * self.H], axis=1)


class LensLook(Effect):
    type = "lens_look"
    needs_ctx = True

    def __init__(self, W, H, fps, intensity=0.6, params=None, seed=0):
        super().__init__(W, H, fps, intensity, params, seed)
        p = self.p
        self.ctx = None
        self.sc = H / LH
        self.palette = str(p.get("palette", "thermal"))
        self.lut = palette_lut(self.palette)
        self.pmix = float(p.get("palette_mix", 0.75))
        self.dof = float(p.get("dof", 0.8))
        self.dof_mode = str(p.get("dof_mode", "both"))
        self.bloom = float(p.get("bloom", 0.5))
        self.bloom_thr = float(p.get("bloom_threshold", 0.55))
        self.ca = float(p.get("ca", 1.0))
        self.led = float(p.get("led", 0.5))
        self.cell = float(p.get("cell", CELL))
        self.tear = float(p.get("tear", 1.0))
        self.grain = float(p.get("grain", 0.06))
        self.vig = float(p.get("vignette", 0.42))
        self.keep_red = bool(p.get("keep_red", False))
        self.lum = str(p.get("lum", "gray"))
        self.cam = LensCam(W, H, p)
        self.shot_dur = float(p.get("shot_dur", 0) or 0)
        self._noise = None
        self._vig = None
        self._rng = np.random.default_rng(seed + 5)
        self._ledcache: tuple | None = None
        self.last_cam = None
        self.forced = None   # (rot, zoom, aim) set per frame by the terminal card
        self.cuts = [float(c) for c in p.get("cuts", [])]

    # ---- helpers
    def bind(self, ctx):
        self.ctx = ctx
        if not self.shot_dur:
            self.shot_dur = ctx.dur

    def _grain_tiles(self, k: int):
        """(pos, neg) uint8 HxWx3 noise tiles (equal on all channels), cycled; amplitude = grain·255·0.5."""
        if self._noise is None:
            r = np.random.default_rng(1234)
            amp = max(0.0, self.grain) * 255 * 0.5
            self._noise = []
            for _ in range(4):
                n = (r.random((self.H, self.W), dtype=np.float32) - 0.5) * 2 * amp
                pos = np.clip(n, 0, 255).astype(np.uint8)
                neg = np.clip(-n, 0, 255).astype(np.uint8)
                self._noise.append((cv2.merge([pos] * 3), cv2.merge([neg] * 3)))
        return self._noise[k % 4]

    def _vignette(self) -> np.ndarray:
        if self._vig is None:
            ys = (np.arange(self.H, dtype=np.float32) - 0.5 * self.H) / self.H * 1.15
            xs = (np.arange(self.W, dtype=np.float32) - 0.5 * self.W) / self.H * 0.85
            v = np.clip(1.0 - self.vig * (ys[:, None] ** 2 + xs[None, :] ** 2), 0, 1)
            self._vig = cv2.merge([(v * 255).astype(np.uint8)] * 3)
        return self._vig

    def _blur_levels(self, rgb_w: np.ndarray, radii: list[float]) -> list[np.ndarray]:
        """Bokeh-weighted blurs at working (quarter) resolution. rgb_w is float32 HxWx4 (rgb*w, w)."""
        out = []
        h, w = rgb_w.shape[:2]
        quarter = None
        for r in radii:
            sig = max(0.5, r / 2.0)
            if sig > 6:
                if quarter is None:
                    quarter = cv2.resize(rgb_w, (max(2, w // 2), max(2, h // 2)), interpolation=cv2.INTER_AREA)
                b = cv2.GaussianBlur(quarter, (0, 0), sig / 2.0)
                b = cv2.resize(b, (w, h), interpolation=cv2.INTER_LINEAR)
            else:
                b = cv2.GaussianBlur(rgb_w, (0, 0), sig)
            out.append(b[..., :3] / np.maximum(b[..., 3:4], 1e-4))
        return out

    # ---- main
    def __call__(self, img, t, env):
        S = min(1.0, self.I * env * (1.0 if self.I <= 1 else 1.0))
        if S <= 0.004:
            return img
        ctx = self.ctx
        H, W, sc = self.H, self.W, self.sc
        lock = ctx.lock if ctx else 0.0
        cut = self._cut_level(t) if not ctx else max(ctx.cut, self._cut_level(t))
        x = t / max(self.shot_dur, 1e-3)
        frame_k = int(t * 30)
        src = img
        # 1) tear
        shake = lock + cut
        if shake > 0.02 and self.tear > 0:
            src = src.copy()
            band = max(4, int(16 * sc * src.shape[0] / H))
            nb = src.shape[0] // band + 1
            rng = np.random.default_rng(self.seed * 7919 + frame_k)
            hit = rng.random(nb) >= 0.93 - 0.18 * min(shake, 1.2)
            sh = ((rng.random(nb) - 0.5) * 220 * sc * min(shake, 1.2) * self.tear).astype(int)
            for b in np.nonzero(hit)[0]:
                y0, y1 = b * band, min(src.shape[0], (b + 1) * band)
                src[y0:y1] = np.roll(src[y0:y1], int(sh[b] * src.shape[1] / W), axis=1)
        # 2) perspective plane
        z_map = None
        rot, zoom, aim = self.forced if self.forced is not None else self.cam.solve(x, t)
        self.last_cam = (self.cam, rot, zoom, aim)
        if ctx:
            ctx.cam = self.last_cam
            ctx.palette = self.palette
        sh_, sw_ = src.shape[:2]
        if self.forced is None and self.cam.static_identity:
            warped = src if (sw_, sh_) == (W, H) else cv2.resize(src, (W, H), interpolation=cv2.INTER_AREA)
            bx = by = None
        else:
            bx, by, zq, _ = self.cam.maps(rot, zoom, aim)
            mx = cv2.resize(bx * (sw_ / self.cam.LW), (W, H), interpolation=cv2.INTER_LINEAR)
            my = cv2.resize(by * (sh_ / LH), (W, H), interpolation=cv2.INTER_LINEAR)
            warped = cv2.remap(src, mx, my, cv2.INTER_LINEAR,
                               borderMode=cv2.BORDER_REFLECT101 if self.cam.fit == "cover" else cv2.BORDER_CONSTANT)
            z_map = zq
        # 3) depth of field
        frame = self._dof(warped, bx, by, z_map, rot, zoom, aim, S)
        # 4) CA + palette
        frame = self._palette(frame, lock, cut, S)
        # 5) bloom + LED
        frame, led_k = self._bloom_led(frame, bx, by, zoom, 1.0, z_map)
        # 6) exposure, vignette, flicker, grain
        frame = self._post(frame, t, cut, frame_k, S)
        if S < 0.999:
            frame = cv2.addWeighted(img, 1 - S, frame, S, 0)
        return frame

    def _cut_level(self, t: float) -> float:
        lv = 0.0
        for c in self.cuts:
            if t >= c:
                lv = max(lv, math.exp(-(t - c) / 0.07))
        return lv

    def _focus_px(self, bx, by, zoom, aim):
        ctx = self.ctx
        if ctx is not None and ctx.focus is not None:
            return ctx.focus
        f = self.p.get("focus")
        if f:
            return float(f[0]) * self.W, float(f[1]) * self.H
        return self.W / 2, self.H / 2

    def _dof(self, img, bx, by, z_map, rot, zoom, aim, S):
        self._rlog = None
        if self.dof <= 0.01 or S < 0.05:
            return img
        H, W, sc = self.H, self.W, self.sc
        ds = 4
        hh, hw = max(2, H // ds), max(2, W // ds)
        gh, gw = (z_map.shape if z_map is not None else (max(2, H // 4), max(2, W // 4)))
        fx, fy = self._focus_px(bx, by, zoom, aim)
        # map the focus (source px) into the camera's output space for the radial term
        if self.ctx is not None and self.last_cam:
            cam, r_, z_, a_ = self.last_cam
            fo = cam.project(np.array([[fx, fy]]), r_, z_, a_)[0]
        else:
            fo = np.array([fx, fy])
        px = (np.arange(gw, dtype=np.float32) + 0.5) * (W / gw)
        py = (np.arange(gh, dtype=np.float32) + 0.5) * (H / gh)
        PX, PY = np.meshgrid(px, py)
        coc = np.zeros((gh, gw), np.float32)
        if z_map is not None and self.dof_mode in ("plane", "both"):
            # depth at the focus point on the tilted plane
            R = _rot(*rot)
            eu, ev = R[:, 0], R[:, 1]
            K = FOCAL * LH / zoom
            fl = (np.array([fx / W * self.cam.LW, fy / H * LH]) - np.array(aim)) / K
            zf = float((np.array([0, 0, 1.0]) + eu * fl[0] + ev * fl[1])[2])
            coc += np.clip(self.dof * 190 * np.abs(1 - zf / np.maximum(z_map, 0.05)), 0, 46)
        if self.dof_mode in ("radial", "both") or z_map is None:
            d = np.hypot(PX - fo[0], PY - fo[1]) / (0.5 * math.hypot(W, H))
            coc += (self.dof * 20.0) * smoothstep(0.12, 0.85, d).astype(np.float32)
        coc = np.clip(coc, 0, 46) * sc          # radius in output px
        zz = z_map if z_map is not None else 1.0
        self._rlog = (coc * (LH / (zoom * H)) * zz).astype(np.float32)
        if float(coc.max()) < 0.7:
            return img
        radii = [r for r in (3.0, 8.0, 18.0, 38.0) if r * 0.5 <= float(coc.max()) * 1.4 + 2.5][:4]
        small = cv2.resize(img, (hw, hh), interpolation=cv2.INTER_AREA).astype(np.float32) / 255.0
        lum = small[..., 1]
        w = 1.0 + 7.0 * (lum * lum * lum)
        rgb_w = cv2.merge([small[..., 0] * w, small[..., 1] * w, small[..., 2] * w, w])
        lv_r = [r * sc for r in radii]
        levels = self._blur_levels(rgb_w, [r / ds for r in lv_r])  # working-res radii
        coc_full = cv2.resize(coc, (hw, hh), interpolation=cv2.INTER_LINEAR) / ds
        rr = [0.0] + [r / ds for r in lv_r]
        acc = np.zeros_like(small)
        wsum = np.zeros((hh, hw), np.float32)
        for k, lvk in enumerate([small] + levels):
            if k == 0:
                wk = np.clip(1 - coc_full / max(rr[1], 1e-3), 0, 1) if len(rr) > 1 else np.ones_like(coc_full)
            else:
                lo = rr[k - 1]
                up = np.clip((coc_full - lo) / max(rr[k] - lo, 1e-3), 0, 1)
                if k + 1 < len(rr):
                    hi = rr[k + 1]
                    up = np.minimum(up, np.clip((hi - coc_full) / max(hi - rr[k], 1e-3), 0, 1))
                wk = up
            acc += wk[..., None] * lvk
            wsum += wk
        blurred = np.clip(acc * (255.0 / np.maximum(wsum[..., None], 1e-4)), 0, 255).astype(np.uint8)
        up_img = cv2.resize(blurred, (W, H), interpolation=cv2.INTER_LINEAR)
        sharp = np.clip(1 - coc / 1.2, 0, 1)
        if float(sharp.max()) <= 0.01:
            return up_img
        w8 = cv2.resize((sharp * 255).astype(np.uint8), (W, H), interpolation=cv2.INTER_LINEAR)
        w3 = cv2.merge([w8, w8, w8])
        return cv2.add(cv2.multiply(img, w3, scale=1 / 255.0), cv2.multiply(up_img, cv2.bitwise_not(w3), scale=1 / 255.0))

    def _plane_scale(self, plane: np.ndarray, k: float) -> np.ndarray:
        if abs(k) < 4e-4:
            return plane
        M = np.array([[1 + k, 0, -k * self.W / 2], [0, 1 + k, -k * self.H / 2]], np.float32)
        return cv2.warpAffine(plane, M, (self.W, self.H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)

    def _palette(self, img, lock, cut, S):
        k = (0.006 + 0.016 * lock + 0.008 * cut) * self.ca
        red = None
        if self.keep_red:
            r = img[..., 2].astype(np.int16) - img[..., 1].astype(np.int16)
            red = np.clip(r * 1.4 / 255.0, 0, 1).astype(np.float32)
        if self.lut is None:
            if k < 4e-4:
                return img
            b, g, r = cv2.split(img)
            return cv2.merge([self._plane_scale(b, -k), g, self._plane_scale(r, k)])
        Y = img[..., 1] if self.lum == "g" else cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        Yr, Yb = self._plane_scale(Y, k), self._plane_scale(Y, -k)
        lut = self.lut
        mapped = cv2.merge([cv2.LUT(Yb, np.ascontiguousarray(lut[:, 0])), cv2.LUT(Y, np.ascontiguousarray(lut[:, 1])),
                            cv2.LUT(Yr, np.ascontiguousarray(lut[:, 2]))])
        pm = self.pmix
        out = mapped if pm >= 0.999 else cv2.addWeighted(img, 1 - pm, mapped, pm, 0)
        if red is not None and float(red.max()) > 0.02:
            col = np.array(RED_BGR, np.float32)
            out = np.clip(out.astype(np.float32) * (1 - red[..., None]) + col * red[..., None], 0, 255).astype(np.uint8)
        return out

    def _bloom_led(self, img, bx, by, zoom, S, zq=None):
        H, W, sc = self.H, self.W, self.sc
        out = img
        if self.bloom > 0.01:
            q = cv2.resize(img, (W // 4, H // 4), interpolation=cv2.INTER_AREA)
            lum = cv2.cvtColor(q, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255.0
            thr = self.bloom_thr
            lum = np.clip((lum - thr) / max(1e-3, 1 - thr), 0, 1)
            glow = cv2.GaussianBlur(lum, (0, 0), max(1.0, 26 * sc / 4 * 0.55))
            gi = np.clip(glow * 1.6 * 255, 0, 255).astype(np.uint8)
            lut = self.lut if self.lut is not None else np.stack([np.arange(256)] * 3, 1).astype(np.uint8)
            col = cv2.merge([cv2.LUT(gi, np.ascontiguousarray(lut[:, c])) for c in range(3)]).astype(np.float32)
            col *= (glow * 0.75 * self.bloom * S)[..., None]
            out = cv2.add(out, cv2.resize(np.clip(col, 0, 255).astype(np.uint8), (W, H), interpolation=cv2.INTER_LINEAR))
        led_base = float(self.led)
        if led_base > 0.02 and self.cell * zoom * sc > 1.4:
            out = self._led(out, bx, by, zoom, zq)
        return out, led_base

    _TILE_T = 8

    def _led_tile(self) -> np.ndarray:
        if getattr(self, "_tile", None) is None:
            T = self._TILE_T
            u = (np.arange(T, dtype=np.float32) + 0.5) / T            # 0..1 across the cell
            cu_x, cu_y = u - 0.5, u - 0.5
            sub = 0.5 + 0.5 * np.cos(6.2831853 * (u[:, None] - np.array([0.8333, 0.5, 0.1667], np.float32)[None]))  # BGR
            rowm = 1 - smoothstep(0.28, 0.5, np.abs(cu_y))
            colm = 1 - smoothstep(0.36, 0.5, np.abs(cu_x))
            m = rowm[:, None, None] * (colm[:, None] * (0.4 + sub) * 1.3)[None, :, :]
            self._tile = np.clip(m * 100, 0, 255).astype(np.uint8)
        return self._tile

    def _led(self, img, bx, by, zoom, zq):
        """Equal-area RGB LED cells sampled from a one-cell texture (BORDER_WRAP), faded by the local cell size and
        by the blur radius, like the shader's ledAmt."""
        H, W = self.H, self.W
        T, cell = self._TILE_T, self.cell
        if bx is None:
            key = (W, H, round(zoom, 3))
            if getattr(self, "_flatmaps", (None,))[0] != key:
                xs = (np.arange(W, dtype=np.float32) + 0.5) / W * self.cam.LW / cell * T
                ys = (np.arange(H, dtype=np.float32) + 0.5) / H * LH / cell * T
                self._flatmaps = (key, np.ascontiguousarray(np.broadcast_to(xs[None], (H, W))), np.ascontiguousarray(np.broadcast_to(ys[:, None], (H, W))))
            _, mx, my = self._flatmaps
            zl = None
        else:
            mx = cv2.resize(bx, (W, H), interpolation=cv2.INTER_LINEAR) * (T / cell)
            my = cv2.resize(by, (W, H), interpolation=cv2.INTER_LINEAR) * (T / cell)
            zl = zq
        mx = np.mod(mx, T).astype(np.float32)
        my = np.mod(my, T).astype(np.float32)
        lm = cv2.remap(self._led_tile(), mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_WRAP)
        # per-pixel amount (low-res): local cell size on screen (from the map's Jacobian) × out-of-focus fade
        if zl is not None:
            gh, gw = zl.shape
            dxs, dys = W / gw, H / gh
            dbx_dx = np.gradient(bx, axis=1) / dxs
            dby_dx = np.gradient(by, axis=1) / dxs
            dbx_dy = np.gradient(bx, axis=0) / dys
            dby_dy = np.gradient(by, axis=0) / dys
            foot = np.maximum(np.hypot(dbx_dx, dby_dx), np.hypot(dbx_dy, dby_dy))      # logical px per output px
            cell_px = cell / np.maximum(foot, 1e-4)
        else:
            gh, gw = max(2, H // 8), max(2, W // 8)
            cell_px = np.full((gh, gw), cell * H / LH / zoom * zoom, np.float32)
            cell_px[:] = cell * zoom * H / LH
        amt = smoothstep(2.6, 5.0, cell_px).astype(np.float32)
        rl = getattr(self, "_rlog", None)
        if rl is not None:
            rl = cv2.resize(rl, (gw, gh), interpolation=cv2.INTER_LINEAR)
            amt *= (1 - smoothstep(0.8, 3.5, rl / cell)).astype(np.float32)
        amt *= float(self.led) * 0.9
        if float(amt.max()) < 0.02:
            return img
        a8 = cv2.resize((np.clip(amt, 0, 1) * 255).astype(np.uint8), (W, H), interpolation=cv2.INTER_LINEAR)
        a3 = cv2.merge([a8, a8, a8])
        lit = cv2.multiply(img, lm, scale=1 / 100.0)
        return cv2.add(cv2.multiply(img, cv2.bitwise_not(a3), scale=1 / 255.0), cv2.multiply(lit, a3, scale=1 / 255.0))

    def _post(self, img, t, cut, frame_k, S):
        H, W = self.H, self.W
        f = img
        if self.vig > 0:
            f = cv2.multiply(f, self._vignette(), scale=1 / 255.0)
        rows = np.clip((1.0 - (0.035 - 0.035 * np.sin(np.arange(H, dtype=np.float32) * 0.9 - t * 55.0))) * 255, 0, 255).astype(np.uint8)
        f = cv2.multiply(f, np.ascontiguousarray(np.broadcast_to(rows[:, None, None], (H, W, 3))), scale=1 / 255.0)
        if cut > 0.01:
            f = cv2.convertScaleAbs(f, alpha=1 + cut * 1.1, beta=cut * 0.06 * 255)
        if self.grain > 0:
            pos, neg = self._grain_tiles(frame_k + self.seed)
            f = cv2.subtract(cv2.add(f, pos), neg)
        return f
