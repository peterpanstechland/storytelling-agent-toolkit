"""GL Transitions ported to NumPy / OpenCV (CPU, no OpenGL needed).

Source: https://github.com/gl-transitions/gl-transitions — the collection is MIT (2017-present gl-transitions
contributors) and every transition file carries its own author + license header; all the ones below are
`// License: MIT`. Each function here is a re-implementation of that GLSL, credited to its original author:

  gl_cross_zoom        rectalogic (rendermix CrossZoom; after evanw/glfx.js zoomBlur, MIT)
  gl_crosswarp         Eke Péter
  gl_directional_warp  pschroen
  gl_ripple            gre
  gl_morph             paniq
  gl_overexposure      Ben Zhang
  gl_dreamy_zoom       Zeh Fernando
  gl_swirl             Sergey Kosarevsky
  gl_fly_eye           gre
  gl_cube              gre
  gl_glitch_displace   Matt DesLauriers
  gl_film_burn         Anastasia Dunbar
  gl_luma_melt         0gust1 (uses Ashima Arts / Ian McEwan simplex noise, MIT)

Differences from the GLSL originals: bilinear `cv2.remap` instead of GPU texture fetches, clamp-to-edge borders, and
the sample-heavy ones (cross zoom: 41 taps, film burn: 50 taps) use fewer taps at half resolution with the same
per-pixel jitter. Colour order is BGR; the shaders' `.rg+.b` maths is applied to R/G/B, not B/G/R.
Uniform defaults are the collection's defaults. progress p = 0 → clip A, 1 → clip B. GLSL uv has y pointing up.
"""
from __future__ import annotations

import math

import cv2
import numpy as np


def smoothstep(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def fract(x):
    return x - np.floor(x)


def mix(a, b, t):
    return a + (b - a) * t


class GL:
    """uv grid + texture fetch for one frame size."""

    def __init__(self, W: int, H: int):
        self.W, self.H = W, H
        self.ratio = W / H
        xs = (np.arange(W, dtype=np.float32) + 0.5) / W
        ys = 1.0 - (np.arange(H, dtype=np.float32) + 0.5) / H
        self.U, self.V = np.meshgrid(xs, ys)

    def tex(self, img: np.ndarray, u, v) -> np.ndarray:
        H, W = img.shape[:2]
        mx = np.asarray(u, np.float32) * W - 0.5
        my = (1.0 - np.asarray(v, np.float32)) * H - 0.5
        if mx.ndim == 0:
            mx = np.full((self.H, self.W), mx, np.float32)
        if my.ndim == 0:
            my = np.full((self.H, self.W), my, np.float32)
        if mx.shape != img.shape[:2] or my.shape != img.shape[:2]:
            mx = cv2.resize(mx, (W, H)) if mx.shape != img.shape[:2] else mx
            my = cv2.resize(my, (W, H)) if my.shape != img.shape[:2] else my
        return cv2.remap(img, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)


# ---------------------------------------------------------------------------------------------- transitions
def cross_zoom(g: GL, A, B, p, strength=0.4):
    """rectalogic — crossfade through a strong zoom blur (jittered taps, half-res)."""
    H, W = A.shape[:2]
    e = lambda t: 0.0 if t <= 0 else 1.0 if t >= 1 else (0.5 * 2 ** (10 * (2 * t - 1)) if t < 0.5 else 0.5 * (-(2 ** (-10 * (2 * t - 1))) + 2))
    dissolve = e(p)
    s = strength * 0.5 * (1 - math.cos(2 * math.pi * p))          # Sinusoidal_easeInOut(0, strength, 0.5, p)
    M = mix(A, B, dissolve)
    cx, cy = (0.25 + 0.5 * p) * W, 0.5 * H
    n = 12
    rng = np.random.default_rng(7)
    off = rng.random((H, W), dtype=np.float32)[..., None]
    acc = np.zeros_like(M)
    tot = np.zeros((H, W, 1), np.float32)
    for k in range(n + 1):
        pc = (k + off) / (n + 1)
        w = 4.0 * (pc - pc * pc)
        sc = 1.0 - pc[..., 0] * s                                   # sample = centre + (uv - centre) * (1 - pc*s)
        mx = cx + (np.arange(W, dtype=np.float32)[None] - cx) * sc
        my = cy + (np.arange(H, dtype=np.float32)[:, None] - cy) * sc
        acc += cv2.remap(M, mx.astype(np.float32), my.astype(np.float32), cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE) * w
        tot += w
    return acc / tot


cross_zoom.res = 0.5


def crosswarp(g, A, B, p):
    x = smoothstep(0.0, 1.0, p * 2.0 + g.U - 1.0)
    a = g.tex(A, (g.U - 0.5) * (1 - x) + 0.5, (g.V - 0.5) * (1 - x) + 0.5)
    b = g.tex(B, (g.U - 0.5) * x + 0.5, (g.V - 0.5) * x + 0.5)
    return mix(a, b, x[..., None])


def directional_warp(g, A, B, p, smoothness=0.1, direction=(-1.0, 1.0)):
    v = np.array(direction, np.float32)
    v = v / np.linalg.norm(v)
    v = v / (abs(v[0]) + abs(v[1]))
    d = v[0] * 0.5 + v[1] * 0.5
    m = 1.0 - smoothstep(-smoothness, 0.0, v[0] * g.U + v[1] * g.V - (d - 0.5 + p * (1.0 + smoothness)))
    a = g.tex(A, (g.U - 0.5) * (1 - m) + 0.5, (g.V - 0.5) * (1 - m) + 0.5)
    b = g.tex(B, (g.U - 0.5) * m + 0.5, (g.V - 0.5) * m + 0.5)
    return mix(a, b, m[..., None])


def ripple(g, A, B, p, amplitude=100.0, speed=50.0):
    dx, dy = g.U - 0.5, g.V - 0.5
    dist = np.sqrt(dx * dx + dy * dy)
    k = (np.sin(p * dist * amplitude - p * speed) + 0.5) / 30.0 * p
    a = g.tex(A, g.U + dx * k, g.V + dy * k)
    return mix(a, B, float(smoothstep(0.2, 1.0, p)))


def morph(g, A, B, p, strength=0.1):
    def off(img):
        r, gg, b = img[..., 2], img[..., 1], img[..., 0]
        return ((r + b) * 0.5) * 2 - 1, ((gg + b) * 0.5) * 2 - 1
    oax, oay = off(A)
    obx, oby = off(B)
    ocx, ocy = (oax + obx) * 0.5 * strength, (oay + oby) * 0.5 * strength
    a = g.tex(A, g.U + ocx * p, g.V + ocy * p)
    b = g.tex(B, g.U - ocx * (1 - p), g.V - ocy * (1 - p))
    return mix(a, b, p)


def overexposure(g, A, B, p, strength=0.6):
    s = math.sin(math.pi * p) * strength
    return A * (1.0 - p + s) + B * (p + s)


def dreamy_zoom(g, A, B, p, rotation=6.0, scale=1.2):
    DEG2RAD = 0.03926990816987241548078304229099      # as written in the original shader
    phase = p * 2.0 if p < 0.5 else (p - 0.5) * 2.0
    ang_off = rotation * DEG2RAD * phase if p < 0.5 else -rotation * DEG2RAD * (1 - phase)
    new_scale = mix(1.0, scale, phase) if p < 0.5 else mix(scale, 1.0, phase)
    px = (g.U - 0.5) / new_scale * g.ratio
    py = (g.V - 0.5) / new_scale
    angle = np.arctan2(py, px) + ang_off
    dist = np.sqrt(px * px + py * py)
    u = np.cos(angle) * dist / g.ratio + 0.5
    v = np.sin(angle) * dist + 0.5
    c = g.tex(A if p < 0.5 else B, u, v)
    return c + (phase if p < 0.5 else 1.0 - phase)


def swirl(g, A, B, p):
    ux, uy = g.U - 0.5, g.V - 0.5
    dist = np.sqrt(ux * ux + uy * uy)
    percent = np.clip(1.0 - dist, 0, 1)
    amt = mix(0.0, 1.0, p / 0.5) if p <= 0.5 else mix(1.0, 0.0, (p - 0.5) / 0.5)
    th = percent * percent * amt * 8.0 * 3.14159
    S, C = np.sin(th), np.cos(th)
    nx, ny = ux * C - uy * S + 0.5, ux * S + uy * C + 0.5
    return mix(g.tex(A, nx, ny), g.tex(B, nx, ny), p)


def fly_eye(g, A, B, p, size=0.04, zoom=50.0, color_separation=0.3):
    inv = 1.0 - p
    dx, dy = size * np.cos(zoom * g.U), size * np.sin(zoom * g.V)
    to = g.tex(B, g.U + inv * dx, g.V + inv * dy)
    r = g.tex(A, g.U + p * dx * (1 - color_separation), g.V + p * dy * (1 - color_separation))[..., 2]
    gg = g.tex(A, g.U + p * dx, g.V + p * dy)[..., 1]
    b = g.tex(A, g.U + p * dx * (1 + color_separation), g.V + p * dy * (1 + color_separation))[..., 0]
    return to * p + np.dstack([b, gg, r]) * inv


def _xskew(px, py, persp, center):
    x = mix(px, 1.0 - px, center)
    y = (py - 0.5 * (1.0 - persp) * x) / (1.0 + (persp - 1.0) * x)
    d = abs(center - 0.5)
    sx = 0.5 / d * (1.0 if center < 0.5 else -1.0)
    return (x - (0.5 - d)) * sx + (0.0 if center < 0.5 else 1.0), y


def cube(g, A, B, p, persp=0.7, unzoom=0.3, reflection=0.4, floating=3.0):
    uz = unzoom * 2.0 * (0.5 - abs(0.5 - p))
    px, py = -uz * 0.5 + (1.0 + uz) * g.U, -uz * 0.5 + (1.0 + uz) * g.V
    fx, fy = _xskew((px - p) / max(1.0 - p, 1e-4), py, 1.0 - mix(p, 0.0, persp), 0.0)
    tx, ty = _xskew(px / max(p, 1e-4), py, mix(p * p, 1.0, persp), 1.0)
    inb = lambda x, y: (x > 0) & (x < 1) & (y > 0) & (y < 1)
    in_f, in_t = inb(fx, fy), inb(tx, ty)
    out = np.zeros_like(A)
    # background: dim reflections of both faces below the cube
    for img, qx, qy in ((A, fx, fy), (B, tx, ty)):
        rx, ry = qx, qy * -1.2 - floating / 100.0
        m = inb(rx, ry)
        if m.any():
            out += (g.tex(img, np.clip(rx, 0, 1), np.clip(ry, 0, 1)) * (reflection * (1.0 - ry))[..., None]) * m[..., None]
    out = np.where(in_t[..., None], g.tex(B, np.clip(tx, 0, 1), np.clip(ty, 0, 1)), out)
    out = np.where(in_f[..., None], g.tex(A, np.clip(fx, 0, 1), np.clip(fy, 0, 1)), out)
    return out


def glitch_displace(g, A, B, p):
    def ease1(t):
        return t if t in (0.0, 1.0) else (0.5 * 2 ** (20 * t - 10) if t < 0.5 else -0.5 * 2 ** (10 - t * 20) + 1.0)

    def ease2(t):
        return t if t == 1.0 else 1.0 - 2 ** (-10 * t)

    def displace(tex, tex_depth, dot_depth, strength):
        r, gg = tex[..., 2], tex[..., 1]
        dx = (r * (dot_depth - tex_depth) + tex_depth * dot_depth) * strength
        dy = (gg * (dot_depth - tex_depth) + tex_depth * dot_depth) * strength
        return g.U + dx, g.V + dy

    c1, c2 = A, B
    u1, v1 = displace(c1, 0.7, 0.33, 1.0 - ease1(p))
    u2, v2 = displace(c2, 0.5, 0.33, ease2(p))
    d1, d2 = g.tex(B, u1, v1), g.tex(A, u2, v2)
    val = ease1(p)
    m = np.minimum(d2, d1)
    gray = (m[..., 2] * 0.299 + m[..., 1] * 0.587 + m[..., 0] * 0.114)[..., None]
    d2g = np.repeat(gray, 3, axis=2) * 2.0
    c1 = mix(c1, d2g, float(smoothstep(0.0, 0.5, p)))
    c2 = mix(c2, d1, float(smoothstep(1.0, 0.5, p)))
    return mix(c1, c2, val)


def _rand1(c, seed):
    return math.modf(math.sin(c * 24.9898 + seed) * 43758.5453)[0] % 1.0


def _sigmoid(x, a):
    b = (x * 2.0) ** a / 2.0
    if x > 0.5:
        b = 1.0 - (2.0 - x * 2.0) ** a / 2.0
    return b


def film_burn(g, A, B, p, seed=2.31):
    """Anastasia Dunbar — light-leak film burn (light field at 1/4 res, 12-tap radial blur at half res)."""
    H, W = A.shape[:2]
    fr = lambda x: x - math.floor(x)
    rnd = lambda c: fr(math.sin(c * 24.9898 + seed) * 43758.5453)

    def rand2(x, y):
        return fr(math.sin(x * 12.9898 + y * 78.233) * 43758.5453)

    def random(cx, cy, shft):
        cx, cy = cx + 10.0, cy + 10.0
        a = fr(math.sin(cx * (12.9898 + math.floor(shft) * 0.5) + cy * (78.233 + seed)) * 43758.5453)
        b = fr(math.sin(cx * (12.9898 + math.floor(shft + 1.0) * 0.5) + cy * (78.233 + seed)) * 43758.5453)
        return mix(a, b, _sigmoid(fr(shft), 2.0))

    def smooth_random(cx, cy, shft):
        fx, fy = fr(cx), fr(cy)
        ix, iy = math.floor(cx), math.floor(cy)
        top = mix(random(ix, iy, shft), random(ix + 1, iy, shft), _sigmoid(fx, 2.0))
        bot = mix(random(ix, iy + 1, shft), random(ix + 1, iy + 1, shft), _sigmoid(fx, 2.0))
        return mix(top, bot, _sigmoid(fy, 2.0))

    qh, qw = max(2, H // 4), max(2, W // 4)
    xs = (np.arange(qw, dtype=np.float32) + 0.5) / qw
    ys = 1.0 - (np.arange(qh, dtype=np.float32) + 0.5) / qh
    PX, PY = np.meshgrid(xs, ys)
    f = np.zeros((qh, qw), np.float32)
    for i in range(13):
        f += np.sin(PX * rnd(i) * 6.0 + p * 8.0 + rnd(i + 1.43)) * np.sin(PY * rnd(i + 4.4) * 6.0 + p * 6.0 + rnd(i + 2.4))
        cxp, cyp = smooth_random(p * 1.3, p * 1.3, i + 1.0), smooth_random(p * 0.5, p * 0.5, i + 6.25)
        f += 1.0 - np.clip(np.sqrt((PX - cxp) ** 2 + (PY - cyp) ** 2) * mix(20.0, 70.0, rnd(i)), 0, 1)
    f = (f + 4.0) / 11.0
    exps = (1.0, 2.0 - math.sin(p * math.pi), 1.3)          # R, G, B
    mul = (1.0, 0.7, 0.6)
    chans = [np.abs(f * m) ** e * math.copysign(1.0, e) * math.sin(p * math.pi) for m, e in zip(mul, exps)]
    glow = cv2.resize(np.dstack(chans[::-1]).astype(np.float32), (W, H), interpolation=cv2.INTER_LINEAR)   # → BGR
    # zoom jitter + radial blur of the blended pair
    s = math.sin(p * math.pi)
    zoom = 1.0 + smooth_random(p * 5.0, p * 5.0, 6.3) * s * 0.05
    blend = mix(A, B, _sigmoid(p, 10.0))
    hh, hw = H // 2, W // 2
    small = cv2.resize(blend, (hw, hh), interpolation=cv2.INTER_AREA)
    amt = s * 0.03
    rng = np.random.default_rng(11)
    acc = np.zeros_like(small)
    n = 12
    xs2 = (np.arange(hw, dtype=np.float32) + 0.5) / hw - 0.5
    ys2 = (np.arange(hh, dtype=np.float32) + 0.5) / hh - 0.5
    for k in range(n):
        a = 2 * math.pi * k / n
        r = rng.random((hh, hw), dtype=np.float32) + amt
        u = (xs2[None] * zoom + np.cos(a) * r * amt) + 0.5
        v = (ys2[:, None] * zoom + np.sin(a) * r * amt) + 0.5
        acc += cv2.remap(small, (u * hw - 0.5).astype(np.float32), (v * hh - 0.5).astype(np.float32), cv2.INTER_LINEAR,
                         borderMode=cv2.BORDER_REPLICATE)
    return cv2.resize(acc / n, (W, H), interpolation=cv2.INTER_LINEAR) + glow


def _snoise_x(xv: np.ndarray) -> np.ndarray:
    """2-D simplex noise (Ashima Arts / Ian McEwan, MIT) at (x, 0), vectorised over x."""
    C = (0.211324865405187, 0.366025403784439, -0.577350269189626, 0.024390243902439)
    mod289 = lambda a: a - np.floor(a * (1.0 / 289.0)) * 289.0
    permute = lambda a: mod289(((a * 34.0) + 1.0) * a)
    vx, vy = xv.astype(np.float64), np.zeros_like(xv, np.float64)
    s = (vx + vy) * C[1]
    ix, iy = np.floor(vx + s), np.floor(vy + s)
    t = (ix + iy) * C[0]
    x0x, x0y = vx - ix + t, vy - iy + t
    i1x = (x0x > x0y).astype(np.float64)
    i1y = 1.0 - i1x
    x12 = [x0x + C[0] - i1x, x0y + C[0] - i1y, x0x + C[2], x0y + C[2]]
    ix, iy = mod289(ix), mod289(iy)
    p = [permute(permute(iy + o) + ix + q) for o, q in ((0.0, 0.0), (i1y, i1x), (1.0, 1.0))]
    m = [np.maximum(0.5 - d, 0.0) for d in (x0x * x0x + x0y * x0y, x12[0] ** 2 + x12[1] ** 2, x12[2] ** 2 + x12[3] ** 2)]
    m = [mm * mm * mm * mm for mm in m]
    xg = [2.0 * (pp * C[3] - np.floor(pp * C[3])) - 1.0 for pp in p]
    h = [np.abs(a) - 0.5 for a in xg]
    ox = [np.floor(a + 0.5) for a in xg]
    a0 = [a - o for a, o in zip(xg, ox)]
    m = [mm * (1.79284291400159 - 0.85373472095314 * (aa * aa + hh * hh)) for mm, aa, hh in zip(m, a0, h)]
    gx = [a0[0] * x0x + h[0] * x0y, a0[1] * x12[0] + h[1] * x12[1], a0[2] * x12[2] + h[2] * x12[3]]
    return 130.0 * (m[0] * gx[0] + m[1] * gx[1] + m[2] * gx[2])


def luma_melt(g, A, B, p, direction=True, l_threshold=0.8, above=False):
    if p <= 0.0:
        return A
    if p >= 1.0:
        return B
    W, H = g.W, g.H
    xs = g.U[0].astype(np.float64)
    sn = _snoise_x(xs)
    cx, cy = 1.0, 1.0 if direction else 0.0
    dist = np.sqrt((cx - g.U) ** 2 + (cy - g.V) ** 2) - p * np.exp(sn)[None, :]
    rr = p - np.modf(np.sin(xs * 12.9898 + 0.1 * 78.233) * 43758.5453)[0] % 1.0
    lum = A[..., 2] * 0.299 + A[..., 1] * 0.587 + A[..., 0] * 0.114
    cond = (dist <= rr[None, :]) & ((lum > l_threshold) if above else (lum < l_threshold))
    m = np.where(cond, 1.0, p ** 3).astype(np.float32)[..., None]
    return mix(A, B, m)


GL_TRANSITIONS = {
    "gl_cross_zoom": (cross_zoom, "穿越缩放模糊叠化（GL Transitions · rectalogic）"),
    "gl_crosswarp": (crosswarp, "交叉扭曲：A 放大冲出、B 缩小就位（GL Transitions · Eke Péter）"),
    "gl_directional_warp": (directional_warp, "斜向扭曲擦除（GL Transitions · pschroen）"),
    "gl_ripple": (ripple, "水波纹扩散叠化（GL Transitions · gre）"),
    "gl_morph": (morph, "色彩位移变形叠化（GL Transitions · paniq）"),
    "gl_overexposure": (overexposure, "过曝叠化（GL Transitions · Ben Zhang）"),
    "gl_dreamy_zoom": (dreamy_zoom, "梦幻缩放旋转 + 闪亮（GL Transitions · Zeh Fernando）"),
    "gl_swirl": (swirl, "漩涡叠化（GL Transitions · Sergey Kosarevsky）"),
    "gl_fly_eye": (fly_eye, "蝇眼透镜 + 色散（GL Transitions · gre）"),
    "gl_cube": (cube, "3D 立方体翻转 + 地面倒影（GL Transitions · gre）"),
    "gl_glitch_displace": (glitch_displace, "位移故障闪入（GL Transitions · Matt DesLauriers）"),
    "gl_film_burn": (film_burn, "胶片烧灼漏光（GL Transitions · Anastasia Dunbar）"),
    "gl_luma_melt": (luma_melt, "亮度融化（GL Transitions · 0gust1）"),
}
CREDITS = {
    "gl_cross_zoom": "rectalogic", "gl_crosswarp": "Eke Péter", "gl_directional_warp": "pschroen", "gl_ripple": "gre",
    "gl_morph": "paniq", "gl_overexposure": "Ben Zhang", "gl_dreamy_zoom": "Zeh Fernando", "gl_swirl": "Sergey Kosarevsky",
    "gl_fly_eye": "gre", "gl_cube": "gre", "gl_glitch_displace": "Matt DesLauriers", "gl_film_burn": "Anastasia Dunbar",
    "gl_luma_melt": "0gust1",
}

_GL_CACHE: dict = {}


def gl_frame(kind: str, a: np.ndarray, b: np.ndarray, x: float) -> np.ndarray:
    """uint8 BGR frames a, b and progress x (0..1) → uint8 BGR."""
    fn = GL_TRANSITIONS[kind][0]
    H, W = a.shape[:2]
    res = getattr(fn, "res", 1.0)
    h, w = (H, W) if res == 1.0 else (int(H * res) // 2 * 2, int(W * res) // 2 * 2)
    key = (w, h)
    g = _GL_CACHE.get(key)
    if g is None:
        if len(_GL_CACHE) > 3:
            _GL_CACHE.clear()
        g = _GL_CACHE[key] = GL(w, h)
    af, bf = a.astype(np.float32) / 255.0, b.astype(np.float32) / 255.0
    if res != 1.0:
        af, bf = cv2.resize(af, (w, h), interpolation=cv2.INTER_AREA), cv2.resize(bf, (w, h), interpolation=cv2.INTER_AREA)
    out = fn(g, af, bf, float(min(1.0, max(0.0, x))))
    if res != 1.0:
        out = cv2.resize(out, (W, H), interpolation=cv2.INTER_LINEAR)
    return np.clip(out * 255.0 + 0.5, 0, 255).astype(np.uint8)
