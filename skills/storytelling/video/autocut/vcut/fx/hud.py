"""tracker_hud — ff-tracking style tracker overlay for real footage.

Hatched boxes (difference-blended 45° stripes), links with a travelling dot, real pixel-coordinate labels, target
brackets, a lock moment (red box, red flash, scanline tear, chromatic-aberration spike) and the collapse → "Done"
pill. Look and geometry follow mrsarac/ff-tracking (MIT, https://github.com/mrsarac/ff-tracking — flat/src/lib.rs
for the boxes, lens/src/lib.rs for links/labels/brackets). Credit: NOTICE.md.

Differences: boxes come from the detector / motion / corner tracker (fx/trackctx.py) or manual points instead of
being generated; positions are projected through the lens_look camera when both are active, so labels show the
real output pixel positions. Tails running off the frame are not drawn.

params: mode, points, max_boxes, locks, lock_hold, collapse_at, collapse_dur, label (pill text), hatch all|target|none,
        color "#rrggbb" ink, lock_color, labels/links/brackets/outline/pill (bool), lock_fx (bool), flash (0..1),
        draw: optional explicit list of parts (hatch, outline, links, labels, brackets, pill)
"""
from __future__ import annotations

import math

import cv2
import numpy as np

from . import fonts
from .effects import Effect

LOCK_BGR = (48, 59, 255)       # #ff3b30
WHITE = (255, 255, 255)
PARTS = ("hatch", "outline", "links", "labels", "brackets", "pill")


def _hex_bgr(v, default):
    if isinstance(v, str) and v.startswith("#") and len(v) == 7:
        return (int(v[5:7], 16), int(v[3:5], 16), int(v[1:3], 16))
    if isinstance(v, (list, tuple)) and len(v) == 3:
        return (int(v[2]), int(v[1]), int(v[0]))
    return default


_HATCH_CACHE: dict = {}


def hatch_mask(W: int, H: int, sc: float, red: bool = False) -> np.ndarray:
    """45° stripes, period 7·sc px, stripe width 2.6/7 (3.2/7 red) — as the ff-tracking SVG pattern."""
    key = (W, H, round(sc, 3), red)
    m = _HATCH_CACHE.get(key)
    if m is None:
        yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
        u = ((xx + yy) * 0.70710678 / (7.0 * sc)) % 1.0
        m = ((u < (3.2 if red else 2.6) / 7.0) * 255).astype(np.uint8)
        if len(_HATCH_CACHE) > 6:
            _HATCH_CACHE.clear()
        _HATCH_CACHE[key] = m
    return m


def draw_quad_box(img: np.ndarray, quad: np.ndarray, *, locked: bool, hatch: bool, outline: bool, ink, sc: float,
                  opacity: float = 1.0) -> None:
    """Hatched box (quad = 4×2 float output px) drawn in place. Hatch inverts pixels (difference with white)."""
    H, W = img.shape[:2]
    q = np.round(quad).astype(np.int32)
    x0, y0 = max(0, int(q[:, 0].min()) - 1), max(0, int(q[:, 1].min()) - 1)
    x1, y1 = min(W, int(q[:, 0].max()) + 2), min(H, int(q[:, 1].max()) + 2)
    if x1 <= x0 or y1 <= y0:
        return
    if hatch:
        poly = np.zeros((y1 - y0, x1 - x0), np.uint8)
        cv2.fillConvexPoly(poly, q - np.array([x0, y0], np.int32), 255)
        hm = hatch_mask(W, H, sc, red=locked)[y0:y1, x0:x1]
        m = (poly > 0) & (hm > 0)
        roi = img[y0:y1, x0:x1]
        if locked:
            roi[m] = (np.array([0, 0, 255], np.float32) * opacity + roi[m].astype(np.float32) * (1 - opacity)).astype(np.uint8)
        else:
            roi[m] = (255 - roi[m].astype(np.float32)) * opacity + roi[m].astype(np.float32) * (1 - opacity)
    if outline:
        cv2.polylines(img, [q], True, LOCK_BGR if locked else ink, max(1, int(round(2.2 * sc))), cv2.LINE_AA)


def rounded_rect(img, x0, y0, x1, y1, r, fill, stroke=None, sw=2):
    r = int(min(r, (x1 - x0) / 2, (y1 - y0) / 2))
    for (cx, cy) in ((x0 + r, y0 + r), (x1 - r, y0 + r), (x0 + r, y1 - r), (x1 - r, y1 - r)):
        cv2.circle(img, (cx, cy), r, fill, -1, cv2.LINE_AA)
    cv2.rectangle(img, (x0 + r, y0), (x1 - r, y1), fill, -1)
    cv2.rectangle(img, (x0, y0 + r), (x1, y1 - r), fill, -1)
    if stroke is not None:
        cv2.ellipse(img, (x0 + r, y0 + r), (r, r), 0, 180, 270, stroke, sw, cv2.LINE_AA)
        cv2.ellipse(img, (x1 - r, y0 + r), (r, r), 0, 270, 360, stroke, sw, cv2.LINE_AA)
        cv2.ellipse(img, (x0 + r, y1 - r), (r, r), 0, 90, 180, stroke, sw, cv2.LINE_AA)
        cv2.ellipse(img, (x1 - r, y1 - r), (r, r), 0, 0, 90, stroke, sw, cv2.LINE_AA)
        cv2.line(img, (x0 + r, y0), (x1 - r, y0), stroke, sw, cv2.LINE_AA)
        cv2.line(img, (x0 + r, y1), (x1 - r, y1), stroke, sw, cv2.LINE_AA)
        cv2.line(img, (x0, y0 + r), (x0, y1 - r), stroke, sw, cv2.LINE_AA)
        cv2.line(img, (x1, y0 + r), (x1, y1 - r), stroke, sw, cv2.LINE_AA)


def draw_done_pill(img, cx, cy, text, sc, k: float, size_scale: float = 1.0) -> None:
    """The ff-tracking 'Done' pill: dark rounded rect, white stroke, check icon. k = 0..1 reveal."""
    if k <= 0.01:
        return
    size = max(10, int(34 * sc * size_scale))
    tw = fonts.text_width(text, size, True)
    w, h = tw + 150 * sc * size_scale, 78 * sc * size_scale
    k = min(1.0, k)
    s = 0.85 + 0.15 * (1 - (1 - k) ** 3)
    w, h = w * s, h * s
    layer = img.copy()
    x0, y0, x1, y1 = int(cx - w / 2), int(cy - h / 2), int(cx + w / 2), int(cy + h / 2)
    rounded_rect(layer, x0, y0, x1, y1, h / 2, (29, 29, 29), WHITE, max(2, int(3 * sc)))
    ix, iy = x0 + int(h * 0.62), int(cy)
    cv2.circle(layer, (ix, iy), int(h * 0.27), WHITE, -1, cv2.LINE_AA)
    r = h * 0.27
    pts = np.array([[ix - r * 0.45, iy + r * 0.02], [ix - r * 0.1, iy + r * 0.38], [ix + r * 0.5, iy - r * 0.38]], np.int32)
    cv2.polylines(layer, [pts], False, (17, 17, 17), max(2, int(3.5 * sc)), cv2.LINE_AA)
    fonts.draw_text(layer, text, ix + h * 0.5, cy + size * 0.34, size, WHITE, bold=True, opacity=min(1.0, max(0.0, (k - 0.25) / 0.5)))
    a = min(1.0, k * 1.6)
    img[:] = cv2.addWeighted(img, 1 - a, layer, a, 0) if a < 0.999 else layer


class TrackerHUD(Effect):
    type = "tracker_hud"
    needs_ctx = True

    def __init__(self, W, H, fps, intensity=0.8, params=None, seed=0):
        super().__init__(W, H, fps, intensity, params, seed)
        p = self.p
        self.ctx = None
        self.sc = H / 1080.0
        self.ink = _hex_bgr(p.get("color"), WHITE)
        self.hatch = str(p.get("hatch", "all"))
        draw = p.get("draw")
        self.parts = set(draw) if draw else {k for k in PARTS if p.get(k, True)}
        if not draw and not p.get("pill", True):
            self.parts.discard("pill")
        self.lock_fx = bool(p.get("lock_fx", True))
        self.flash = float(p.get("flash", 0.18))
        self.label = str(p.get("label", "Done"))
        self.order = str(p.get("order", "x"))
        self.n = 0

    def bind(self, ctx):
        self.ctx = ctx

    def _jit(self, k: int, amp: float) -> tuple[float, float]:
        r = np.random.default_rng((self.seed * 31 + self.n * 17 + k * 101) & 0xFFFFFFFF)
        return (r.random() - 0.5) * 2 * amp * self.sc, (r.random() - 0.5) * 2 * amp * self.sc

    def __call__(self, img, t, env):
        S = min(1.0, self.I * env)
        ctx = self.ctx
        if S <= 0.01 or ctx is None:
            return img
        self.n += 1
        sc, H, W = self.sc, self.H, self.W
        out = img
        # lock FX when there is no lens_look to do the tear / CA
        if self.lock_fx and ctx.lock > 0.05 and ctx.cam is None:
            out = self._lock_fx(img, ctx.lock)
        else:
            out = img.copy()
        boxes = list(ctx.boxes)
        c = ctx.collapse
        tgt = ctx.target
        if not boxes:
            return out
        ink = self.ink if (self.p.get("color") or getattr(ctx, "palette", "") != "paper") else (20, 20, 20)
        ids = {id(b): k for k, b in enumerate(boxes)}
        keyf = {"reading": lambda b: (round(b.cy / (H * 0.12)), b.cx), "id": lambda b: b.id}.get(self.order, lambda b: b.cx)
        order = sorted(boxes, key=keyf)
        # geometry in output px
        items = []
        for k, b in enumerate(order):
            ax = min(1.0, (b.age + 1) / max(1, int(0.28 * self.fps))) if b.age >= 0 else 1.0
            ax = 1 - (1 - ax) ** 3
            jx, jy = self._jit(k, 1.6)
            cx, cy, w, h = b.cx + jx / max(sc, 1e-6) * 0, b.cy, b.w, b.h
            if tgt is not None and c > 0 and b is not tgt:
                cx, cy = cx + (tgt.cx - cx) * c, cy + (tgt.cy - cy) * c
                w, h = w + (tgt.w - w) * c, h + (tgt.h - h) * c
            w, h = max(8 * sc, w * ax), max(8 * sc, h * ax)
            corners = np.array([[cx - w / 2, cy - h / 2], [cx + w / 2, cy - h / 2], [cx + w / 2, cy + h / 2],
                                [cx - w / 2, cy + h / 2]], np.float64)
            if ctx.cam is not None:
                cam, rot, zoom, aim = ctx.cam
                quad = cam.project(corners, rot, zoom, aim)
                cen = cam.project(np.array([[cx, cy]]), rot, zoom, aim)[0]
            else:
                quad, cen = corners, np.array([cx, cy])
            quad = quad + np.array(self._jit(k + 50, 1.0))
            fade = 1.0 - (c if (tgt is not None and b is not tgt) else 0.0) * 0.85
            items.append((b, quad, cen, fade))
        locked_now = ctx.locked
        for b, quad, cen, fade in items:
            is_t = b is tgt
            lk = locked_now and (is_t or tgt is None)
            hatch_on = "hatch" in self.parts and (self.hatch == "all" or (self.hatch == "target" and is_t))
            if fade < 0.15:
                continue
            draw_quad_box(out, quad, locked=lk, hatch=hatch_on, outline="outline" in self.parts, ink=ink, sc=sc,
                          opacity=min(1.0, fade * (0.85 if hatch_on and not lk else 1.0)))
        # links with a travelling dot
        if "links" in self.parts and c < 0.6 and len(items) > 1:
            lw = max(1, int(round(1.3 * sc)))
            for k in range(1, len(items)):
                a, b = items[k - 1][2], items[k][2]
                p = (self.n * 0.17 + k * 0.31) % 1.0
                cv2.line(out, (int(a[0]), int(a[1])), (int(b[0]), int(b[1])), ink, lw, cv2.LINE_AA)
                cv2.circle(out, (int(a[0] + (b[0] - a[0]) * p), int(a[1] + (b[1] - a[1]) * p)), max(2, int(3 * sc)), ink, -1, cv2.LINE_AA)
        done_now = "pill" not in self.parts and ctx.done >= 0
        # labels (real output pixel coordinates), alternating above / below
        if "labels" in self.parts and c < 0.5 and not done_now:
            fs = max(9, int(19 * sc))
            taken: list[tuple[float, float]] = []
            for k, (b, quad, cen, fade) in enumerate(items):
                is_t = b is tgt
                lk = locked_now and (is_t or tgt is None)
                below = k % 2 == 1 and not lk
                if below:
                    corner = quad[3]
                    y = corner[1] + 24 * sc
                else:
                    corner = quad[0]
                    y = corner[1] - 9 * sc
                col = LOCK_BGR if lk else ink
                cv2.circle(out, (int(cen[0]), int(cen[1])), max(2, int(3.2 * sc)), col, -1, cv2.LINE_AA)
                free = lk or all(abs(tx - corner[0]) > 190 * sc or abs(ty - y) > 26 * sc for tx, ty in taken)
                if not free:
                    continue
                taken.append((corner[0], y))
                txt = (f"LOCK x: {cen[0]:.0f} y: {cen[1]:.0f}" if lk else f"x: {cen[0]:.0f} y: {cen[1]:.0f}")
                fonts.draw_text(out, txt, corner[0], y, fs, col)
        # brackets on the target
        if "brackets" in self.parts and tgt is not None and not done_now:
            for b, quad, cen, fade in items:
                if b is not tgt:
                    continue
                col = LOCK_BGR if ctx.lock > 0.3 or locked_now else ink
                grow = (10 if ctx.lock > 0.3 else 6) * sc
                ctr = quad.mean(axis=0)
                for k in range(4):
                    pnt = quad[k]
                    o = pnt - ctr
                    ln = max(float(np.hypot(*o)), 1e-3)
                    q = pnt + o / ln * grow
                    arms = []
                    for n in (quad[(k + 1) % 4], quad[(k + 3) % 4]):
                        d = n - pnt
                        dl = max(float(np.hypot(*d)), 1e-3)
                        arms.append(q + d / dl * min(18 * sc, dl * 0.4))
                    cv2.polylines(out, [np.round(np.array([arms[1], q, arms[0]])).astype(np.int32)], False, col,
                                  max(1, int(round(2.4 * sc))), cv2.LINE_AA)
        # collapse → pill
        if "pill" in self.parts and ctx.done >= 0 and tgt is not None:
            cx, cy = ctx.project(tgt.cx, tgt.cy)
            cx = min(max(cx, W * 0.25), W * 0.75)
            cy = min(max(cy, H * 0.2), H * 0.8)
            draw_done_pill(out, cx, cy, self.label, sc, min(1.0, ctx.done / 0.25), 1.0 if W >= H else 0.8)
        # lock flash
        if self.flash > 0 and ctx.lock > 0.02 and self.lock_fx:
            f = self.flash * ctx.lock
            red = np.full_like(out, (40, 40, 255))
            out = cv2.addWeighted(out, 1 - f, red, f, 0)
        if S < 0.999:
            out = cv2.addWeighted(img, 1 - S, out, S, 0)
        return out

    def _lock_fx(self, img, lock):
        H, W, sc = self.H, self.W, self.sc
        out = img.copy()
        k = 0.006 + 0.02 * lock
        dx = max(1, int(k * W * 0.5))
        out[..., 2] = np.roll(img[..., 2], dx, axis=1)
        out[..., 0] = np.roll(img[..., 0], -dx, axis=1)
        band = max(4, int(16 * sc))
        rng = np.random.default_rng(self.seed * 7919 + self.n)
        nb = H // band + 1
        hit = rng.random(nb) >= 0.93 - 0.18 * lock
        for b in np.nonzero(hit)[0]:
            y0, y1 = b * band, min(H, (b + 1) * band)
            out[y0:y1] = np.roll(out[y0:y1], int((rng.random() - 0.5) * 220 * sc * lock), axis=1)
        return out
