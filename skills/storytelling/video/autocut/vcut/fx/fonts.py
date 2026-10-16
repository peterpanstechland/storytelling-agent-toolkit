"""Tiny glyph-atlas text renderer for HUD overlays (Pillow if present, OpenCV Hershey otherwise).

Fonts are looked up on the system (monospace for the HUD, a CJK face for Chinese labels). Nothing is bundled.
Override with env VCUT_HUD_FONT / VCUT_HUD_FONT_CJK or `hud.font` / `hud.font_cjk` in settings.yaml
(JetBrains Mono / JetBrains Mono Slab are OFL fonts: install them yourself and point `hud.font` at the .ttf).
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np

from .. import config

try:  # optional
    from PIL import Image, ImageDraw, ImageFont
except Exception:  # noqa: BLE001
    Image = ImageDraw = ImageFont = None  # type: ignore[assignment]

MONO_CANDIDATES = [
    "C:/Windows/Fonts/consola.ttf", "C:/Windows/Fonts/lucon.ttf", "C:/Windows/Fonts/cour.ttf",
    "/System/Library/Fonts/Menlo.ttc", "/System/Library/Fonts/Monaco.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", "/usr/share/fonts/dejavu/DejaVuSansMono.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf", "/usr/share/fonts/TTF/DejaVuSansMono.ttf",
]
MONO_BOLD = [
    "C:/Windows/Fonts/consolab.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationMono-Bold.ttf", "/usr/share/fonts/dejavu/DejaVuSansMono-Bold.ttf",
]
CJK_CANDIDATES = [
    "C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/msyh.ttf", "C:/Windows/Fonts/simhei.ttf", "C:/Windows/Fonts/simsun.ttc",
    "/System/Library/Fonts/PingFang.ttc", "/System/Library/Fonts/STHeiti Medium.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc", "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/usr/share/fonts/wenquanyi/wqy-microhei/wqy-microhei.ttc",
]


def have_pillow() -> bool:
    return ImageFont is not None


def _first(paths: list[str]) -> str | None:
    for p in paths:
        if p and Path(p).is_file():
            return p
    return None


@lru_cache(maxsize=1)
def font_paths() -> dict[str, str | None]:
    hcfg = config.settings().get("hud") or {}
    mono = os.environ.get("VCUT_HUD_FONT") or hcfg.get("font") or ""
    cjk = os.environ.get("VCUT_HUD_FONT_CJK") or hcfg.get("font_cjk") or ""
    mono = mono if mono and Path(mono).is_file() else _first(MONO_CANDIDATES)
    bold = _first(MONO_BOLD) or mono
    cjk = cjk if cjk and Path(cjk).is_file() else _first(CJK_CANDIDATES)
    if not cjk:  # last resort: any Noto/WenQuanYi CJK face under the usual Linux font roots
        import glob
        for root in ("/usr/share/fonts", "/usr/local/share/fonts"):
            hits = sorted(glob.glob(f"{root}/**/*CJK*.tt[cf]", recursive=True) + glob.glob(f"{root}/**/wqy*.tt[cf]", recursive=True)
                          + glob.glob(f"{root}/**/*CJK*.otf", recursive=True))
            if hits:
                cjk = hits[0]
                break
    return {"mono": mono, "bold": bold, "cjk": cjk}


def is_cjk(ch: str) -> bool:
    o = ord(ch)
    return o >= 0x2E80 and (o <= 0xA4CF or 0xAC00 <= o <= 0xD7AF or 0xF900 <= o <= 0xFAFF or 0xFE30 <= o <= 0xFE4F
                            or 0xFF00 <= o <= 0xFFEF)


@lru_cache(maxsize=64)
def _font(path: str, size: int):
    return ImageFont.truetype(path, size)


@lru_cache(maxsize=4096)
def glyph(ch: str, size: int, bold: bool = False) -> tuple[np.ndarray, int, int, float]:
    """(alpha uint8 HxW, left offset, top offset above the baseline, advance px). Empty alpha for spaces."""
    size = max(6, int(size))
    if ImageFont is None:
        (tw, th), base = cv2.getTextSize(ch, cv2.FONT_HERSHEY_SIMPLEX, size / 34.0, 1)
        return np.zeros((0, 0), np.uint8), 0, 0, float(size * 0.6)
    paths = font_paths()
    key = "cjk" if (is_cjk(ch) and paths["cjk"]) else ("bold" if bold else "mono")
    path = paths.get(key) or paths.get("mono")
    if not path:
        return np.zeros((0, 0), np.uint8), 0, 0, float(size * 0.6)
    f = _font(path, size)
    adv = float(f.getlength(ch)) if ch != "\t" else size * 2.4
    if not ch.strip():
        return np.zeros((0, 0), np.uint8), 0, 0, adv
    pad = size // 2 + 2
    im = Image.new("L", (int(adv) + 2 * pad + size, size * 2 + 2 * pad), 0)
    ImageDraw.Draw(im).text((pad, pad + size), ch, font=f, fill=255, anchor="ls")
    a = np.asarray(im)
    ys, xs = np.nonzero(a)
    if len(ys) == 0:
        return np.zeros((0, 0), np.uint8), 0, 0, adv
    y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
    return np.ascontiguousarray(a[y0:y1, x0:x1]), int(x0 - pad), int(pad + size - y0), adv


def advance(size: int, ch: str = "0") -> float:
    return glyph(ch, size)[3]


def text_width(text: str, size: int, bold: bool = False) -> float:
    return sum(glyph(c, size, bold)[3] for c in text)


def blit_alpha(img: np.ndarray, a: np.ndarray, x: int, y: int, color: tuple[int, int, int], opacity: float = 1.0) -> None:
    h, w = a.shape[:2]
    H, W = img.shape[:2]
    x0, y0, x1, y1 = max(0, x), max(0, y), min(W, x + w), min(H, y + h)
    if x1 <= x0 or y1 <= y0:
        return
    sub = a[y0 - y:y1 - y, x0 - x:x1 - x]
    al = sub.astype(np.float32)[..., None] * (opacity / 255.0)
    roi = img[y0:y1, x0:x1]
    col = np.array(color, np.float32)
    img[y0:y1, x0:x1] = np.clip(roi.astype(np.float32) * (1 - al) + col * al, 0, 255).astype(np.uint8)


def draw_text(img: np.ndarray, text: str, x: float, y: float, size: int, color: tuple[int, int, int] = (255, 255, 255),
              *, bold: bool = False, opacity: float = 1.0, anchor: str = "l") -> float:
    """Draw `text` with its baseline at y. anchor l | c | r on x. Returns the drawn width."""
    width = text_width(text, size, bold)
    if ImageFont is None:  # Hershey fallback (ASCII only)
        s = "".join(c if ord(c) < 128 else "?" for c in text)
        (tw, th), _ = cv2.getTextSize(s, cv2.FONT_HERSHEY_SIMPLEX, size / 34.0, 1)
        px = x - (tw / 2 if anchor == "c" else tw if anchor == "r" else 0)
        cv2.putText(img, s, (int(px), int(y)), cv2.FONT_HERSHEY_SIMPLEX, size / 34.0, color, 1, cv2.LINE_AA)
        return float(tw)
    px = x - (width / 2 if anchor == "c" else width if anchor == "r" else 0)
    for ch in text:
        a, ox, oy, adv = glyph(ch, size, bold)
        if a.size:
            blit_alpha(img, a, int(round(px + ox)), int(round(y - oy)), color, opacity)
        px += adv
    return width
