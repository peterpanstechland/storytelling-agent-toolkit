"""Per-frame looks, all procedural (no third-party assets → no licensing issues).

Every effect is an object: Effect(type, W, H, fps, intensity, params, seed)(img_bgr_uint8, t_local, env) → img.
`env` (0..1) is the time envelope computed by the engine (window fade or beat pulses); intensity scales it.
Heavy maths runs at reduced resolution and is upsampled; typical cost 2–15 ms per 1080p frame.
"""
from __future__ import annotations

import math

import cv2
import numpy as np


def to_u8_full(layer: np.ndarray, alpha: float, W: int, H: int) -> np.ndarray:
    """Low-res float layer → scaled uint8 at full size (resize after quantizing = cheap)."""
    small = np.clip(layer * alpha, 0, 255).astype(np.uint8)
    if small.shape[1] != W or small.shape[0] != H:
        small = cv2.resize(small, (W, H), interpolation=cv2.INTER_LINEAR)
    if small.ndim == 2:
        small = cv2.cvtColor(small, cv2.COLOR_GRAY2BGR)
    return small


def screen(base: np.ndarray, layer: np.ndarray, alpha: float = 1.0) -> np.ndarray:
    """Screen blend; layer may be low-res float (0..255) or full-res uint8."""
    H, W = base.shape[:2]
    lay = layer if (layer.dtype == np.uint8 and alpha >= 0.999 and layer.shape[:2] == (H, W)) else to_u8_full(layer, alpha, W, H)
    inv = cv2.multiply(cv2.bitwise_not(base), cv2.bitwise_not(lay), scale=1 / 255.0)
    return cv2.bitwise_not(inv)


class Effect:
    type = "base"

    def __init__(self, W: int, H: int, fps: int, intensity: float = 0.6, params: dict | None = None, seed: int = 0):
        self.W, self.H, self.fps = W, H, fps
        self.I = float(intensity)
        self.p = dict(params or {})
        self.seed = seed
        self.rng = np.random.default_rng(seed)
        self.n = 0

    def __call__(self, img: np.ndarray, t: float, env: float = 1.0) -> np.ndarray:
        self.n += 1
        a = self.I * env
        if a <= 0.003:
            return self.idle(img, t)
        return self.apply(img, t, a)

    def idle(self, img: np.ndarray, t: float) -> np.ndarray:
        return img

    def apply(self, img: np.ndarray, t: float, a: float) -> np.ndarray:  # pragma: no cover - abstract
        return img


# ------------------------------------------------------------------ glitch family
class Glitch(Effect):
    type = "glitch"

    def apply(self, img, t, a):
        H, W = img.shape[:2]
        r = np.random.default_rng(self.seed * 7919 + self.n)
        # bursts: glitch is intermittent unless driven by beats (env already pulsing)
        if not self.p.get("on") and r.random() > 0.35 + 0.55 * min(1.0, a):
            return img
        out = img.copy()
        # 1) RGB split
        dx = int((0.004 + 0.022 * a) * W * (0.5 + r.random()))
        out[..., 2] = np.roll(img[..., 2], dx, axis=1)
        out[..., 0] = np.roll(img[..., 0], -dx // 2, axis=1)
        # 2) block displacement bands
        for _ in range(int(2 + 9 * a)):
            h = int(H * r.uniform(0.008, 0.07))
            y = int(r.uniform(0, H - h))
            shift = int(r.uniform(-1, 1) * W * 0.12 * a)
            band = np.roll(out[y:y + h], shift, axis=1)
            if r.random() < 0.25:
                band = band[..., r.permutation(3)]
            if r.random() < 0.12:
                band = 255 - band
            out[y:y + h] = band
        # 3) a few quantized "macroblocks"
        for _ in range(int(4 * a)):
            bw, bh = int(W * r.uniform(0.03, 0.12)), int(H * r.uniform(0.02, 0.08))
            x0, y0 = int(r.uniform(0, W - bw)), int(r.uniform(0, H - bh))
            blk = out[y0:y0 + bh, x0:x0 + bw]
            out[y0:y0 + bh, x0:x0 + bw] = (blk // 64 * 64 + 32).astype(np.uint8)
        # 4) scanlines
        out[::3] = (out[::3].astype(np.uint16) * (1.0 - 0.25 * a)).astype(np.uint8)
        # 5) vertical jump
        if a > 0.5 and r.random() < 0.3:
            out = np.roll(out, int(H * 0.02 * r.uniform(-1, 1)), axis=0)
        return out


class RGBSplit(Effect):
    """Lens chromatic aberration: R scaled up, B scaled down around the centre."""
    type = "rgb_split"

    def apply(self, img, t, a):
        H, W = img.shape[:2]
        k = 0.004 + 0.016 * a
        out = img.copy()
        for ch, s in ((2, 1 + k), (0, 1 - k)):
            M = cv2.getRotationMatrix2D((W / 2, H / 2), 0, s)
            out[..., ch] = cv2.warpAffine(img[..., ch], M, (W, H), borderMode=cv2.BORDER_REFLECT)
        return out


class Scanlines(Effect):
    type = "scanlines"

    def apply(self, img, t, a):
        out = img.copy()
        period = max(2, img.shape[0] // 360)
        out[::period] = (out[::period].astype(np.float32) * (1 - 0.35 * a)).astype(np.uint8)
        return out


# ------------------------------------------------------------------ light
class LightLeak(Effect):
    """Warm, drifting light leaks (procedural)."""
    type = "light_leak"
    PALETTES = {
        "warm": [(40, 120, 255), (20, 60, 255), (80, 200, 255)],
        "magenta": [(200, 60, 255), (120, 40, 255), (60, 160, 255)],
        "cool": [(255, 180, 60), (255, 120, 120), (200, 255, 200)],
    }

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        r = np.random.default_rng(self.seed + 11)
        self.blobs = [(r.uniform(0, 1), r.uniform(0, 1), r.uniform(0.2, 0.55), r.uniform(0.15, 0.45), r.uniform(0, 6.28))
                      for _ in range(3)]
        self.colors = self.PALETTES.get(self.p.get("palette", "warm"), self.PALETTES["warm"])
        self.lw, self.lh = max(16, self.W // 10), max(9, self.H // 10)
        yy, xx = np.mgrid[0:self.lh, 0:self.lw]
        self.xx, self.yy = xx / self.lw, yy / self.lh

    def apply(self, img, t, a):
        layer = np.zeros((self.lh, self.lw, 3), np.float32)
        for (bx, by, rad, spd, ph), col in zip(self.blobs, self.colors):
            cx = (bx + spd * t * 0.6 + 0.15 * math.sin(t * 0.9 + ph)) % 1.6 - 0.3
            cy = by + 0.2 * math.sin(t * 0.6 + ph * 2)
            d2 = ((self.xx - cx) / rad) ** 2 + ((self.yy - cy) / (rad * 1.4)) ** 2
            g = np.exp(-d2 * 2.2)
            layer += g[..., None] * np.array(col, np.float32)
        return screen(img, layer, min(1.0, 0.9 * a))


class Flare(Effect):
    """Anamorphic lens flare: glow + horizontal streak + ghosts mirrored through the centre."""
    type = "flare"

    def apply(self, img, t, a):
        H, W = img.shape[:2]
        sw, sh = W // 4, H // 4
        x = float(self.p.get("x", 0.15 + 0.7 * ((t * float(self.p.get("speed", 0.12))) % 1.0)))
        y = float(self.p.get("y", 0.18))
        sx, sy = x * sw, y * sh
        layer = np.zeros((sh, sw, 3), np.float32)
        cv2.circle(layer, (int(sx), int(sy)), int(sw * 0.02), (255, 255, 255), -1, cv2.LINE_AA)
        glow = cv2.GaussianBlur(layer, (0, 0), sw * 0.03) * 6
        streak = np.zeros_like(layer)
        cv2.ellipse(streak, (int(sx), int(sy)), (int(sw * 0.6), max(1, int(sh * 0.004))), 0, 0, 360, (255, 200, 120), -1, cv2.LINE_AA)
        streak = cv2.GaussianBlur(streak, (0, 0), sh * 0.006)
        ghosts = np.zeros_like(layer)
        cx, cy = sw / 2, sh / 2
        for f, rr, col in ((-0.3, 0.05, (120, 255, 140)), (0.35, 0.025, (255, 140, 200)), (-0.7, 0.09, (255, 180, 90)),
                           (0.6, 0.04, (90, 200, 255)), (1.3, 0.07, (200, 120, 255))):
            gx, gy = cx + (cx - sx) * f, cy + (cy - sy) * f
            cv2.circle(ghosts, (int(gx), int(gy)), int(sw * rr), col, -1, cv2.LINE_AA)
        ghosts = cv2.GaussianBlur(ghosts, (0, 0), max(0.8, sw * 0.004)) * 0.38
        lay = glow + streak * 1.4 + ghosts
        return screen(img, lay, min(1.0, a))


class Flash(Effect):
    """White flash (exposure blow-out) — env should be a pulse (beat / transition)."""
    type = "flash"

    def apply(self, img, t, a):
        k = min(1.0, a)
        return cv2.addWeighted(img, 1.0 - k, np.full_like(img, 255), k, 0)


class Glow(Effect):
    """Bloom: bright areas bleed light (cyber / dreamy looks)."""
    type = "glow"

    def apply(self, img, t, a):
        H, W = img.shape[:2]
        small = cv2.resize(img, (W // 4, H // 4), interpolation=cv2.INTER_AREA).astype(np.float32)
        bright = np.clip(small - float(self.p.get("threshold", 150)), 0, 255) * 2.0
        bloom = cv2.GaussianBlur(bright, (0, 0), max(2.0, W / 160))
        return screen(img, bloom, min(1.0, a))


# ------------------------------------------------------------------ energy
class SpeedLines(Effect):
    """Anime speed lines converging to the centre (changes every frame)."""
    type = "speed_lines"

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.n_lines = 170

    def apply(self, img, t, a):
        H, W = img.shape[:2]
        sw, sh = W // 2, H // 2
        r = np.random.default_rng(self.seed * 31 + self.n)
        mask = np.zeros((sh, sw), np.uint8)
        cx, cy = sw / 2, sh / 2
        R = math.hypot(sw, sh) / 2 * 1.05
        for k in range(self.n_lines):
            if r.random() > 0.55:
                continue
            th = (k + r.random()) / self.n_lines * 2 * math.pi
            r_in = R * r.uniform(0.38, 0.72)
            wdt = r.uniform(0.0015, 0.006) * 2 * math.pi
            p_out1 = (cx + R * math.cos(th - wdt), cy + R * math.sin(th - wdt))
            p_out2 = (cx + R * math.cos(th + wdt), cy + R * math.sin(th + wdt))
            p_in = (cx + r_in * math.cos(th), cy + r_in * math.sin(th))
            cv2.fillConvexPoly(mask, np.array([p_out1, p_out2, p_in], np.int32), 255, cv2.LINE_AA)
        mask = cv2.resize(mask, (W, H), interpolation=cv2.INTER_LINEAR)
        mask = cv2.multiply(mask, np.full_like(mask, 255), scale=min(1.0, a) / 255.0)
        col = np.full_like(img, 0)
        col[:] = self.p.get("color", (255, 255, 255))
        m3 = cv2.cvtColor(mask, cv2.COLOR_GRAY2BGR)
        return cv2.add(cv2.multiply(img, cv2.bitwise_not(m3), scale=1 / 255.0), cv2.multiply(col, m3, scale=1 / 255.0))


class MotionTrail(Effect):
    """Temporal motion blur / echo trail."""
    type = "motion_blur"

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.acc: np.ndarray | None = None

    def idle(self, img, t):
        self.acc = img.astype(np.float32)
        return img

    def apply(self, img, t, a):
        f = img.astype(np.float32)
        k = min(0.82, 0.35 + 0.5 * a)
        self.acc = f if self.acc is None or self.acc.shape != f.shape else self.acc * k + f * (1 - k)
        return np.clip(self.acc, 0, 255).astype(np.uint8)


# ------------------------------------------------------------------ film / retro
class FilmGrain(Effect):
    """Film grain + gate weave + flicker + occasional dust/scratches."""
    type = "grain"

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        r = np.random.default_rng(self.seed + 5)
        gh, gw = max(8, self.H // 2), max(8, self.W // 2)
        self.bank = [cv2.GaussianBlur(r.normal(0, 1, (gh, gw)).astype(np.float32), (0, 0), 0.7) for _ in range(6)]
        ph = r.uniform(0, 6.28, 6)
        self.ph = ph

    def apply(self, img, t, a):
        H, W = img.shape[:2]
        r = np.random.default_rng(self.seed * 13 + self.n)
        out = img
        weave = float(self.p.get("weave", 1.0))
        if weave > 0:  # gate weave: slow sub-pixel wander + tiny scale to hide borders
            dx = (math.sin(t * 2 * math.pi * 0.7 + self.ph[0]) * 0.6 + math.sin(t * 2 * math.pi * 2.3 + self.ph[1]) * 0.4)
            dy = (math.sin(t * 2 * math.pi * 0.5 + self.ph[2]) * 0.6 + math.sin(t * 2 * math.pi * 1.9 + self.ph[3]) * 0.4)
            amp = 0.0022 * W * weave * a
            M = np.array([[1.012, 0, -0.006 * W + dx * amp], [0, 1.012, -0.006 * H + dy * amp]], np.float32)
            out = cv2.warpAffine(out, M, (W, H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
        g = self.bank[self.n % len(self.bank)]
        g = np.roll(g, (int(r.integers(0, g.shape[0])), int(r.integers(0, g.shape[1]))), axis=(0, 1))
        g16 = cv2.resize((g * (20.0 * a)).astype(np.int16), (W, H), interpolation=cv2.INTER_NEAREST)
        flicker = 1.0 + 0.035 * a * math.sin(t * 2 * math.pi * 9.7 + self.ph[4]) * r.uniform(0.5, 1.0)
        out16 = out.astype(np.int16)
        out16 += g16[..., None]
        out = cv2.convertScaleAbs(out16, alpha=flicker)
        if r.random() < 0.10 * a:  # dust specks
            for _ in range(int(r.integers(1, 5))):
                c = (int(r.uniform(0, W)), int(r.uniform(0, H)))
                v = 20 if r.random() < 0.6 else 235
                cv2.ellipse(out, c, (int(r.uniform(1, 5)), int(r.uniform(1, 3))), r.uniform(0, 180), 0, 360, (v, v, v), -1, cv2.LINE_AA)
        if r.random() < 0.05 * a:  # vertical scratch
            x = int(r.uniform(0.1, 0.9) * W)
            cv2.line(out, (x, 0), (x + int(r.uniform(-8, 8)), H), (200, 200, 200), 1, cv2.LINE_AA)
        return out


class VHS(Effect):
    """VHS: chroma bleed, soft luma, scanlines, tracking band, head-switching noise, OSD."""
    type = "vhs"

    def apply(self, img, t, a):
        H, W = img.shape[:2]
        r = np.random.default_rng(self.seed * 17 + self.n)
        small = cv2.resize(img, (max(16, int(W / 2.6)), H), interpolation=cv2.INTER_AREA)
        soft = cv2.resize(small, (W, H), interpolation=cv2.INTER_LINEAR)
        ycc = cv2.cvtColor(soft, cv2.COLOR_BGR2YCrCb).astype(np.float32)
        k = max(3, int(W * 0.018 * (0.5 + a)) | 1)
        for c in (1, 2):
            ch = cv2.blur(ycc[..., c], (k, 1))
            ycc[..., c] = np.roll(ch, int(W * 0.004 * (0.5 + a)), axis=1)
        ycc[..., 1] = (ycc[..., 1] - 128) * 1.15 + 128 + 4 * a
        ycc[..., 0] = ycc[..., 0] * 0.92 + 14 * a  # lifted blacks
        out = cv2.cvtColor(np.clip(ycc, 0, 255).astype(np.uint8), cv2.COLOR_YCrCb2BGR)
        period = max(2, H // 360)
        out[::period] = (out[::period].astype(np.float32) * (1 - 0.22 * a)).astype(np.uint8)
        # tracking band scrolling down
        bh = int(H * 0.05)
        y0 = int(((t * 0.22) % 1.3 - 0.15) * H)
        ys, ye = max(0, y0), min(H, y0 + bh)
        if ye > ys:
            band = out[ys:ye].astype(np.int16)
            band = np.roll(band, int(W * 0.02 * a * r.uniform(-1, 1)), axis=1)
            noise = (r.random((ye - ys, W, 1)) < 0.10 * a) * r.integers(80, 200)
            out[ys:ye] = np.clip(band + noise, 0, 255).astype(np.uint8)
        # head-switching noise at the bottom
        hs = int(H * 0.025)
        for yy in range(H - hs, H, 2):
            out[yy:yy + 2] = np.roll(out[yy:yy + 2], int(W * 0.03 * r.uniform(0.2, 1.0)), axis=1)
        if self.p.get("osd", True):
            fs = H / 720 * 1.1
            th = max(1, int(fs * 2))
            for txt, org in (("PLAY  >", (int(W * 0.05), int(H * 0.1))),
                             (str(self.p.get("stamp", "AM 10:24   MAR. 01 2026")), (int(W * 0.05), int(H * 0.92)))):
                cv2.putText(out, txt, (org[0] + 2, org[1] + 2), cv2.FONT_HERSHEY_SIMPLEX, fs, (0, 0, 0), th + 1, cv2.LINE_AA)
                cv2.putText(out, txt, org, cv2.FONT_HERSHEY_SIMPLEX, fs, (235, 235, 235), th, cv2.LINE_AA)
        return out


class Vignette(Effect):
    type = "vignette"

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        yy, xx = np.mgrid[0:self.H, 0:self.W].astype(np.float32)
        d = np.sqrt(((xx - self.W / 2) / (self.W / 2)) ** 2 + ((yy - self.H / 2) / (self.H / 2)) ** 2) / math.sqrt(2)
        self.mask = np.clip(1.0 - d ** 2.2, 0, 1)[..., None]

    def apply(self, img, t, a):
        m = (1.0 - (1.0 - self.mask[..., 0]) * min(1.0, a * 1.1))
        m3 = cv2.merge([m, m, m])
        return cv2.multiply(img, m3, dtype=cv2.CV_8U) if False else (img * m3).astype(np.uint8)


class BW(Effect):
    type = "bw"

    def apply(self, img, t, a):
        g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        g3 = cv2.cvtColor(g, cv2.COLOR_GRAY2BGR)
        return cv2.addWeighted(img, 1 - min(1.0, a), g3, min(1.0, a), 0)


REGISTRY: dict[str, type[Effect]] = {c.type: c for c in (Glitch, RGBSplit, Scanlines, LightLeak, Flare, Flash, Glow,
                                                         SpeedLines, MotionTrail, FilmGrain, VHS, Vignette, BW)}


def make_effect(kind: str, W: int, H: int, fps: int, intensity: float, params: dict | None = None, seed: int = 0) -> Effect | None:
    cls = REGISTRY.get(kind)
    return cls(W, H, fps, intensity, params, seed) if cls else None


def window_env(t: float, start: float, dur: float | None, total: float, fade: float = 0.12) -> float:
    end = total if dur is None else start + dur
    if t < start or t > end:
        return 0.0
    return min(1.0, (t - start) / fade if fade > 0 else 1.0, (end - t) / fade if fade > 0 and dur is not None else 1.0)
