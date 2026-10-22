"""Premium looks — original NumPy/OpenCV implementations (no third-party code, so no licence strings attached).

Techniques are the widely documented ones (halation + split-tone + S-curve + luma-weighted grain for film emulation;
threshold → horizontal stretch → tint for anamorphic streaks; chroma delay + head wobble + dropouts for analogue video).
Reference reading only (nothing copied): JanLohse/spectral_film_lut & raw2film (MIT), ntsc-rs (MIT/ISC/Apache core),
and public descriptions of anamorphic flares. See references/fx-sources.md.

  film_stock   — film emulation (stock: kodak_warm | teal_orange | fuji_cool | faded | bleach)
  anamorphic   — blue/amber horizontal streak flares off highlights
  vhs_pro      — stronger analogue-video look (ghosting, wobble, dropouts, colour smear, tracking bands)
"""
from __future__ import annotations

import math

import cv2
import numpy as np

from .effects import Effect, screen

# stock: contrast, lift (black point), gain (white point), shadow tint BGR, highlight tint BGR, saturation, halation
STOCKS = {
    "kodak_warm": dict(contrast=0.9, lift=10, gain=0.97, sh=(-4, 0, 4), hi=(-6, 3, 10), sat=1.08, hal=0.55, grain=0.8),
    "teal_orange": dict(contrast=1.1, lift=8, gain=0.98, sh=(10, 4, -8), hi=(-12, 2, 14), sat=1.12, hal=0.35, grain=0.7),
    "fuji_cool": dict(contrast=0.95, lift=9, gain=0.98, sh=(6, 2, -3), hi=(2, 0, -2), sat=1.02, hal=0.3, grain=0.6),
    "faded": dict(contrast=0.7, lift=26, gain=0.92, sh=(6, 2, 0), hi=(0, 4, 8), sat=0.88, hal=0.25, grain=1.0),
    "bleach": dict(contrast=1.25, lift=4, gain=1.0, sh=(0, 0, 0), hi=(0, 0, 0), sat=0.55, hal=0.2, grain=1.1),
}


def _scurve(x: np.ndarray, c: float) -> np.ndarray:
    """c<1 flatter, c>1 harder; smooth S around mid-grey."""
    k = 1.0 + (c - 1.0) * 2.2
    y = 0.5 + 0.5 * np.tanh((x - 0.5) * 2.0 * k) / math.tanh(k)
    return np.clip(y, 0, 1)


class FilmStock(Effect):
    type = "film_stock"

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self._lut = None
        self._lut_key = None

    def _stock(self):
        return STOCKS.get(str(self.p.get("stock", "kodak_warm")), STOCKS["kodak_warm"])

    def _make_lut(self, a: float):
        s = self._stock()
        x = np.arange(256, dtype=np.float32) / 255.0
        curve = _scurve(x, 1.0 + (s["contrast"] - 1.0))
        base = s["lift"] / 255.0 + curve * (s["gain"] - s["lift"] / 255.0)
        lut = np.zeros((256, 1, 3), np.uint8)
        sh = np.clip(1 - x * 2, 0, 1)
        hi = np.clip(x * 2 - 1, 0, 1)
        for c in range(3):
            y = base + (sh * s["sh"][c] + hi * s["hi"][c]) / 255.0
            y = x * (1 - a) + y * a
            lut[:, 0, c] = np.clip(y * 255.0 + 0.5, 0, 255).astype(np.uint8)
        return lut

    def apply(self, img, t, a):
        H, W = img.shape[:2]
        s = self._stock()
        a = min(1.0, a)
        key = round(a, 2)
        if key != self._lut_key:
            self._lut, self._lut_key = self._make_lut(a), key
        lut = self._lut
        out = cv2.LUT(img, lut) if lut.shape[2] == 1 else cv2.merge([cv2.LUT(img[..., c], lut[:, 0, c]) for c in range(3)])
        sat = 1.0 + (s["sat"] - 1.0) * a
        if abs(sat - 1.0) > 0.01:
            gray = cv2.cvtColor(cv2.cvtColor(out, cv2.COLOR_BGR2GRAY), cv2.COLOR_GRAY2BGR)
            out = cv2.addWeighted(out, sat, gray, 1.0 - sat, 0)
        hal = float(self.p.get("halation", s["hal"])) * a
        if hal > 0.01:                                    # red-orange glow around bright edges
            q = cv2.resize(out, (max(8, W // 4), max(8, H // 4)), interpolation=cv2.INTER_AREA)
            lum = cv2.cvtColor(q, cv2.COLOR_BGR2GRAY)
            m = np.clip((lum.astype(np.float32) - 190.0) * 4.0, 0, 255)
            k = max(3, (W // 28) | 1)
            m = cv2.GaussianBlur(m, (k, k), 0)
            glow = np.dstack([m * 0.25, m * 0.62, m * 1.0])
            out = screen(out, glow, 0.9 * hal)
        gr = float(self.p.get("grain", 1.0)) * s["grain"] * a
        if gr > 0.01:
            r = np.random.default_rng(self.seed * 31 + self.n)
            nz = r.integers(0, 256, (max(8, H // 2), max(8, W // 2)), dtype=np.uint8)
            nz = cv2.GaussianBlur(nz, (3, 3), 0)
            nz = cv2.resize(nz, (W, H), interpolation=cv2.INTER_LINEAR)
            noise = (nz.astype(np.int16) - 128) * (0.14 * gr)
            lum = cv2.cvtColor(out, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255.0
            w = (1.0 - np.abs(lum - 0.45) * 1.5).clip(0.25, 1.0)[..., None]            # strongest in the mids
            out = np.clip(out.astype(np.float32) + (noise[..., None] * w), 0, 255).astype(np.uint8)
        weave = float(self.p.get("weave", 0.5)) * a
        if weave > 0.01:
            r = np.random.default_rng(self.seed * 13 + self.n // 2)
            dx, dy = r.normal(0, 0.45 * weave), r.normal(0, 0.35 * weave)
            out = cv2.warpAffine(out, np.float32([[1, 0, dx], [0, 1, dy]]), (W, H), borderMode=cv2.BORDER_REFLECT)
        return out


class Anamorphic(Effect):
    type = "anamorphic"
    TINTS = {"blue": (255, 150, 60), "amber": (60, 150, 255), "white": (255, 255, 255), "teal": (220, 200, 60)}

    def apply(self, img, t, a):
        H, W = img.shape[:2]
        q = cv2.resize(img, (max(16, W // 4), max(16, H // 4)), interpolation=cv2.INTER_AREA)
        lum = cv2.cvtColor(q, cv2.COLOR_BGR2GRAY).astype(np.float32)
        thr = float(self.p.get("threshold", 205))
        m = np.clip((lum - thr) * (255.0 / max(1.0, 255 - thr)), 0, 255)
        k = max(5, int(q.shape[1] * float(self.p.get("length", 0.55))) | 1)
        s = cv2.dilate(m, np.ones((1, max(3, k // 2)), np.uint8))          # keep the streak bright along its length
        s = cv2.blur(cv2.blur(s, (k // 2 | 1, 1)), (k // 3 | 1, 1))
        s = cv2.GaussianBlur(s, (1, 5), 0) * 1.1
        tint = np.array(self.TINTS.get(str(self.p.get("tint", "blue")), self.TINTS["blue"]), np.float32) / 255.0
        layer = s[..., None] * tint
        return screen(img, layer, float(self.p.get("gain", 0.85)) * min(1.0, a * 1.3))


class VHSPro(Effect):
    type = "vhs_pro"

    def apply(self, img, t, a):
        H, W = img.shape[:2]
        a = min(1.0, a)
        r = np.random.default_rng(self.seed * 17 + self.n)
        # luma: soften horizontally + ghost echo
        soft = cv2.resize(cv2.resize(img, (max(16, int(W / (1.6 + 1.4 * a))), H), interpolation=cv2.INTER_AREA), (W, H),
                          interpolation=cv2.INTER_LINEAR)
        ghost = np.roll(soft, max(2, int(W * 0.012)), axis=1)
        out = cv2.addWeighted(soft, 1.0 - 0.22 * a, ghost, 0.22 * a, 0)
        # chroma: delayed and smeared
        ycc = cv2.cvtColor(out, cv2.COLOR_BGR2YCrCb)
        k = max(3, int(W * 0.03 * (0.4 + a)) | 1)
        for c in (1, 2):
            ycc[..., c] = np.roll(cv2.blur(ycc[..., c], (k, 1)), int(W * 0.006 * (0.5 + a)), axis=1)
        ycc[..., 0] = np.clip(ycc[..., 0].astype(np.float32) * 0.93 + 12 * a, 0, 255).astype(np.uint8)
        out = cv2.cvtColor(ycc, cv2.COLOR_YCrCb2BGR)
        # per-row horizontal wobble (slow sine + head-switch curl at the bottom + occasional spike)
        y = np.arange(H, dtype=np.float32)
        shift = np.sin(y * 0.045 + t * 7.0) * (0.0012 * W * a) + np.sin(y * 0.011 - t * 2.1) * (0.0016 * W * a)
        curl = np.clip((y - H * 0.955) / (H * 0.045), 0, 1) ** 2 * W * 0.05 * a * (0.5 + r.random())
        shift = shift + curl
        for _ in range(int(r.integers(0, 3))):
            y0 = int(r.integers(0, H - 8))
            shift[y0:y0 + int(r.integers(2, 9))] += r.normal(0, W * 0.02 * a)
        mx = (np.arange(W, dtype=np.float32)[None, :] + shift[:, None]).astype(np.float32)
        my = np.repeat(y[:, None], W, axis=1)
        out = cv2.remap(out, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
        # scanline dimming + tracking bands
        period = max(2, H // 300)
        out[::period] = (out[::period] * (1 - 0.18 * a)).astype(np.uint8)
        for bi in range(2):
            by = int(((t * (0.17 + 0.09 * bi) + bi * 0.47) % 1.25 - 0.1) * H)
            bh = int(H * (0.025 + 0.02 * bi))
            ys, ye = max(0, by), min(H, by + bh)
            if ye > ys:
                band = np.roll(out[ys:ye], int(W * 0.03 * a * r.uniform(-1, 1)), axis=1).astype(np.int16)
                band += ((r.random((ye - ys, W, 1)) < 0.12 * a) * r.integers(70, 190)).astype(np.int16)
                out[ys:ye] = np.clip(band, 0, 255).astype(np.uint8)
        # dropouts: short bright horizontal streaks
        for _ in range(int(r.integers(0, 1 + int(4 * a)))):
            yy, xx, ln = int(r.integers(0, H)), int(r.integers(0, W)), int(r.integers(W // 20, W // 4))
            out[yy:yy + 1, xx:xx + ln] = np.clip(out[yy:yy + 1, xx:xx + ln].astype(np.int16) + 110, 0, 255).astype(np.uint8)
        return out


EFFECTS = {"film_stock": FilmStock, "anamorphic": Anamorphic, "vhs_pro": VHSPro}
