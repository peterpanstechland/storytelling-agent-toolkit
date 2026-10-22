"""16:9 → 9:16 (and any wide → tall) vertical reframing, decided once per shot.

Modes (`reframe.vertical` in settings.yaml, `reframe_vertical` in project.yaml, or per clip `clip.reframe.mode`):
  smart    (default) per shot: a tracked subject (faces / people / motion / saliency peaks — the TrackCtx detector
           chain) that fits in the window → `follow`; spread-out content or no clear subject → `fit_blur`.
  follow   smoothed subject-following crop, looser than tight cover (window = `loose` × the 9:16 width, default 1.25);
           the small top/bottom gap is filled with a blurred, darkened copy.
  fit_blur full frame scaled to the output width, centred, blurred + darkened copy behind (optional `fit_zoom`).
  fit_bars full frame scaled to width, black bars.
  crop     legacy tight cover crop at `focus_x` (old behaviour).

The decision never changes inside a shot. The follow path uses a dead-zone + Gaussian smoothing + slew-rate limit, so the
window only moves when the subject leaves the middle of the window, and then glides.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import cv2
import numpy as np

VERTICAL_MODES = ("smart", "fit_blur", "fit_bars", "crop")
CLIP_MODES = ("follow", "fit_blur", "fit_bars", "crop")
DEFAULTS = {"vertical": "smart", "loose": 1.25, "fit_zoom": 1.0, "dead_zone": 0.12, "sample_fps": 2.0,
            "min_presence": 0.6, "min_fit": 0.8, "bg_blur": 0.06, "bg_dim": 0.55}


def cfg(pdata: dict | None = None) -> dict:
    from . import config
    out = dict(DEFAULTS)
    out.update({k: v for k, v in ((config.settings().get("reframe") or {})).items() if v is not None})
    if pdata and pdata.get("reframe_vertical"):
        out["vertical"] = pdata["reframe_vertical"]
    if out["vertical"] not in VERTICAL_MODES:
        out["vertical"] = "smart"
    return out


def needs_vertical(src_w: int, src_h: int, W: int, H: int) -> bool:
    """Tall output from a clearly wider source."""
    return bool(src_w and src_h and H > W and (src_w / src_h) > (W / H) * 1.1)


def window_frac(src_w: int, src_h: int, W: int, H: int, loose: float) -> float:
    """Follow window width as a fraction of the source width (1.0 = whole frame)."""
    return float(min(1.0, (src_h * W / H) * loose / src_w))


def content_size(mode: str, src_w: int, src_h: int, W: int, H: int, loose: float = 1.25, fit_zoom: float = 1.0) -> tuple[int, int]:
    """Size of the actual picture inside the W×H frame (the rest is padding)."""
    ev = lambda v: max(2, int(round(v / 2)) * 2)
    if mode == "follow":
        wn = window_frac(src_w, src_h, W, H, loose)
        return W, min(H, ev(W / (wn * src_w / src_h)))
    if mode in ("fit_blur", "fit_bars"):
        z = fit_zoom if mode == "fit_blur" else 1.0
        return W, min(H, ev(W * src_h / src_w * z))
    return W, H


# ------------------------------------------------------------------ decision
def _subjects(boxes, w: int, h: int):
    """Pick the boxes that make up the subject: detections first, then motion, then strong saliency peaks."""
    strong = [b for b in boxes if b.kind not in ("region", "motion")]
    if strong:
        return strong, "detector"
    mot = [b for b in boxes if b.kind == "motion"]
    if mot:
        big = max(b.w * b.h for b in mot)
        return [b for b in mot if b.w * b.h >= 0.35 * big], "motion"
    reg = [b for b in boxes if b.kind == "region"]
    if reg:
        top = max(b.score for b in reg)
        return [b for b in reg if b.score >= 0.75 * top], "saliency"
    return [], "none"


def smooth_path(ts, xs, wn: float, dead: float = 0.12, sigma: float = 0.8, max_rate: float = 0.18) -> list[float]:
    """Dead-zone follow (move only by the amount the subject leaves ±dead·wn of the window centre), then smooth."""
    from .fx.ease import smooth_series
    if not xs:
        return []
    held = float(np.median(xs[: max(1, min(len(xs), 4))]))   # robust start: one noisy first sample must not set the frame
    out = []
    dz = dead * wn
    for x in xs:
        if x - held > dz:
            held = x - dz
        elif held - x > dz:
            held = x + dz
        out.append(held)
    lo, hi = wn / 2, 1 - wn / 2
    sm = smooth_series(out, ts, sigma_s=sigma, max_rate=max_rate) if len(out) > 1 else np.array(out)
    return [float(min(hi, max(lo, v))) for v in sm]


def decide(frames: list[tuple[float, np.ndarray]], src_w: int, src_h: int, W: int, H: int, c: dict | None = None,
           detector=None) -> dict:
    """frames: [(t_src_relative, BGR small)] → {"mode", "track": [[t, x]], "width", "method", "reason"}."""
    from .fx.trackctx import TrackCtx
    c = {**DEFAULTS, **(c or {})}
    wn = window_frac(src_w, src_h, W, H, float(c["loose"]))
    if not frames:
        return {"mode": "fit_blur", "track": [], "width": wn, "method": "none", "reason": "no frames"}
    h, w = frames[0][1].shape[:2]
    ctx = TrackCtx(w, h, 30, 1.0, {"mode": "auto"}, detector=detector) if detector is not None else TrackCtx(w, h, 30, 1.0, {"mode": "auto"})
    prev = None
    obs, n_subj, n_fit, methods = [], 0, 0, set()
    for t, f in frames:
        gray = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY)
        boxes = ctx._detect(f, gray, 1.0, prev)
        prev = gray
        subj, how = _subjects(boxes, w, h)
        if not subj:
            continue
        n_subj += 1
        methods.add(how)
        x0 = min(b.cx - b.w / 2 for b in subj) / w
        x1 = max(b.cx + b.w / 2 for b in subj) / w
        if x1 - x0 <= wn * 0.92:
            n_fit += 1
            obs.append((t, (x0 + x1) / 2))
    presence = n_subj / len(frames)
    fit = n_fit / max(1, n_subj)
    method = "+".join(sorted(methods)) or "none"
    if presence < float(c["min_presence"]) or fit < float(c["min_fit"]) or len(obs) < 1:
        why = "no clear subject" if presence < float(c["min_presence"]) else "content spread wider than the window"
        return {"mode": "fit_blur", "track": [], "width": wn, "method": method,
                "reason": f"{why} (presence {presence:.0%}, fits {fit:.0%})"}
    ts = [o[0] for o in obs]
    xs = smooth_path(ts, [o[1] for o in obs], wn, float(c["dead_zone"]))
    tr = [[round(t, 3), round(x, 4)] for t, x in zip(ts, xs)]
    return {"mode": "follow", "track": tr, "width": round(wn, 4), "method": method,
            "reason": f"subject fits (presence {presence:.0%}, fits {fit:.0%})"}


def analyze_shot(path: Path, start: float, dur: float, src_w: int, src_h: int, W: int, H: int, c: dict | None = None,
                 cache_dir: Path | None = None) -> dict:
    from .fx.track import sample_frames
    from .util import short_hash
    c = {**DEFAULTS, **(c or {})}
    key = None
    if cache_dir is not None:
        st = Path(path).stat()
        key = cache_dir / f"reframe_{short_hash(str(path), st.st_size, int(st.st_mtime), round(start, 3), round(dur, 3), W, H, json.dumps(c, sort_keys=True), n=16)}.json"
        if key.exists():
            try:
                return json.loads(key.read_text("utf-8"))
            except Exception:  # noqa: BLE001
                pass
    aw = 480
    ah = max(2, int(round(aw * src_h / max(1, src_w) / 2)) * 2)
    frames = sample_frames(Path(path), start, dur, float(c["sample_fps"]), aw, ah)
    res = decide(frames, src_w, src_h, W, H, c)
    if key is not None:
        key.parent.mkdir(parents=True, exist_ok=True)
        key.write_text(json.dumps(res, ensure_ascii=False), "utf-8")
    return res


# ------------------------------------------------------------------ compositing
def track_x(track: list[list[float]], t: float, default: float = 0.5) -> float:
    if not track:
        return default
    if t <= track[0][0]:
        return track[0][1]
    for a, b in zip(track, track[1:]):
        if a[0] <= t <= b[0]:
            u = (t - a[0]) / max(1e-6, b[0] - a[0])
            return a[1] + (b[1] - a[1]) * u
    return track[-1][1]


def background(src: np.ndarray, W: int, H: int, blur: float = 0.06, dim: float = 0.55) -> np.ndarray:
    """Cover-scaled, heavily blurred, darkened copy (computed small → cheap)."""
    sw, sh = max(8, W // 8), max(8, H // 8)
    h, w = src.shape[:2]
    s = max(sw / w, sh / h)
    small = cv2.resize(src, (max(sw, int(math.ceil(w * s))), max(sh, int(math.ceil(h * s)))), interpolation=cv2.INTER_AREA)
    y0, x0 = (small.shape[0] - sh) // 2, (small.shape[1] - sw) // 2
    small = small[y0:y0 + sh, x0:x0 + sw]
    k = max(3, int(min(sw, sh) * blur * 4) | 1)
    small = cv2.GaussianBlur(small, (k, k), 0)
    small = cv2.convertScaleAbs(small, alpha=dim)
    return cv2.resize(small, (W, H), interpolation=cv2.INTER_LINEAR)


def compose(content: np.ndarray, W: int, H: int, mode: str, bg_src: np.ndarray | None = None,
            blur: float = 0.06, dim: float = 0.55) -> np.ndarray:
    ch, cw = content.shape[:2]
    if (cw, ch) == (W, H):
        return content
    canvas = np.zeros((H, W, 3), np.uint8) if mode == "fit_bars" else background(content if bg_src is None else bg_src, W, H, blur, dim)
    y0, x0 = (H - ch) // 2, (W - cw) // 2
    canvas[y0:y0 + ch, x0:x0 + cw] = content
    return canvas


def content_rect(mode: str, src_w: int, src_h: int, W: int, H: int, loose: float = 1.25, fit_zoom: float = 1.0) -> tuple[int, int, int, int]:
    cw, ch = content_size(mode, src_w, src_h, W, H, loose, fit_zoom)
    return (W - cw) // 2, (H - ch) // 2, cw, ch
