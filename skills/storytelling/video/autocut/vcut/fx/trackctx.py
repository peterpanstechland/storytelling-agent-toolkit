"""Shared per-clip tracking state for tracker_hud and lens_look (one TrackCtx per clip render).

The engine calls ctx.update(frame, i, t) once per output frame *before* the effects run. Both effects then read
the same boxes / target / focus / lock level, so the depth of field, the hatched boxes and the lock moment agree.

Box sources (params.mode): auto (detector chain + textured-region cluster boxes + motion), faces, person,
motion, corners, manual (params.points = [[t, x, y, (w, h)], …] normalised to the frame) or `provided`
(set_boxes() — used by the terminal card, which knows its glyph positions exactly).
Between detections (every `detect_every` s, default 0.5) boxes follow Lucas-Kanade optical flow.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import cv2
import numpy as np


@dataclass
class Box:
    id: int
    cx: float
    cy: float
    w: float
    h: float
    score: float = 1.0
    kind: str = "region"
    age: int = 0
    miss: int = 0
    label: str = ""

    @property
    def rect(self):
        return self.cx - self.w / 2, self.cy - self.h / 2, self.w, self.h


def _nms(boxes: list[Box], thr: float = 0.35) -> list[Box]:
    keep: list[Box] = []
    for b in sorted(boxes, key=lambda b: -b.score):
        ok = True
        for k in keep:
            x0, y0 = max(b.cx - b.w / 2, k.cx - k.w / 2), max(b.cy - b.h / 2, k.cy - k.h / 2)
            x1, y1 = min(b.cx + b.w / 2, k.cx + k.w / 2), min(b.cy + b.h / 2, k.cy + k.h / 2)
            inter = max(0, x1 - x0) * max(0, y1 - y0)
            if inter / max(1e-6, min(b.w * b.h, k.w * k.h)) > thr:
                ok = False
                break
        if ok:
            keep.append(b)
    return keep


class TrackCtx:
    def __init__(self, W: int, H: int, fps: int, dur: float, params: dict | None = None, beats: list[float] | None = None,
                 seed: int = 0, detector=None):
        p = dict(params or {})
        self.W, self.H, self.fps, self.dur = W, H, fps, float(dur)
        self.p = p
        self.seed = seed
        self.mode = str(p.get("mode", "auto"))
        self.max_boxes = int(p.get("max_boxes", 5))
        self.detect_every = float(p.get("detect_every", 0.5))
        self.beats = beats or []
        self.sc = H / 1080.0
        self._det_factory = detector
        self._det = None
        self._det_tried = False
        self.boxes: list[Box] = []
        self.target: Box | None = None
        self.focus: tuple[float, float] | None = None
        self.palette = ""
        self.cam = None                   # set by lens_look each frame: (LensCam, rot, zoom, aim)
        self.t = 0.0
        self.lock = 0.0                   # 1 on the lock frames, decays (CA / tear / flash)
        self.locked = False               # boxes held red
        self.cut = 0.0
        self.collapse = 0.0               # 0..1
        self.done = -1.0                  # seconds since the "done" pill appeared (<0: not yet)
        self.provided = self.mode == "provided"
        self._next_id = 0
        self._prev_gray = None
        self._last_detect = -1e9
        self._small_w = 480
        self._tgt_since = 0.0
        self.lock_times = self._lock_times()
        self.collapse_at = p.get("collapse_at")
        self.collapse_dur = float(p.get("collapse_dur", 0.45))
        self.points = [list(map(float, q)) for q in (p.get("points") or [])]
        self.events: list[tuple[float, str]] = []   # (t, "lock"|"collapse"|"done") for SFX planning

    # ---- schedule
    def _lock_times(self) -> list[float]:
        lt = self.p.get("locks")
        if lt is not None:
            return sorted(float(x) for x in lt)
        if self.dur <= 0.9:
            return []
        n = int(self.p.get("lock_count", 1))
        cands = [b for b in self.beats if 0.45 <= b <= self.dur - 0.45]
        if cands:
            mid = self.dur * 0.55
            first = min(cands, key=lambda b: abs(b - mid))
            out = [first]
            for b in cands:
                if len(out) >= n:
                    break
                if all(abs(b - o) > 0.8 for o in out):
                    out.append(b)
            return sorted(out)
        return [round(self.dur * 0.55, 3)]

    def set_boxes(self, boxes: list[Box], focus: tuple[float, float] | None = None, target: Box | None = None) -> None:
        self.boxes = boxes
        self.target = target or (boxes[-1] if boxes else None)
        if focus is not None:
            self.focus = focus
        elif self.target is not None:
            self.focus = (self.target.cx, self.target.cy)

    # ---- detection
    def _detector(self):
        if not self._det_tried:
            self._det_tried = True
            if self._det_factory is not None:
                self._det = self._det_factory
            elif self.mode in ("auto", "faces", "person"):
                try:
                    from .track import Detector
                    d = Detector()
                    self._det = d if d.kind in ("yolo", "yunet", "haar") else None
                except Exception:  # noqa: BLE001
                    self._det = None
        return self._det

    def _detect(self, frame: np.ndarray, gray: np.ndarray, scale: float, prev_small) -> list[Box]:
        out: list[Box] = []
        sh, sw = gray.shape
        inv = 1.0 / scale
        if self.mode in ("auto", "faces", "person"):
            det = self._detector()
            if det is not None:
                small = cv2.resize(frame, (sw, sh), interpolation=cv2.INTER_AREA) if scale != 1 else frame
                for d in det(small):
                    if self.mode == "faces" and d.kind != "face":
                        continue
                    if self.mode == "person" and d.kind != "person":
                        continue
                    out.append(Box(-1, d.cx * inv, d.cy * inv, d.w * inv, d.h * inv, 3.0 + float(d.score), d.kind))
        if self.mode in ("auto", "motion") and prev_small is not None:
            diff = cv2.absdiff(gray, prev_small)
            diff = cv2.GaussianBlur(diff, (0, 0), 3)
            m = (diff > max(14, float(diff.mean()) * 3)).astype(np.uint8)
            m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
            n, _, stats, cents = cv2.connectedComponentsWithStats(m)
            for k in range(1, n):
                x, y, w, h, a = stats[k]
                if a > 0.004 * sw * sh:
                    out.append(Box(-1, (x + w / 2) * inv, (y + h / 2) * inv, w * inv * 1.1, h * inv * 1.1,
                                   2.0 + a / (sw * sh) * 10, "motion"))
        if self.mode in ("auto", "corners", "salient") or (self.mode in ("motion", "faces", "person") and not out):
            out += self._salient(gray, prev_small, inv)
        return _nms(out)[: max(self.max_boxes * 2, 6)]

    def _salient(self, gray: np.ndarray, prev_small, inv: float) -> list[Box]:
        """Peaks of (gradient energy × brightness × motion) → boxes sized by the connected region around the peak."""
        sh, sw = gray.shape
        gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
        gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
        sal = cv2.GaussianBlur(cv2.magnitude(gx, gy), (0, 0), max(2.0, sw / 90))
        sal *= 0.35 + cv2.GaussianBlur(gray, (0, 0), 4).astype(np.float32) / 255.0
        if prev_small is not None and prev_small.shape == gray.shape:
            mo = cv2.GaussianBlur(cv2.absdiff(gray, prev_small).astype(np.float32), (0, 0), 5)
            sal *= 1.0 + 2.5 * mo / (float(mo.max()) + 1e-3)
        m = int(sw * 0.04)
        sal[:m] = sal[-m:] = 0
        sal[:, :m] = sal[:, -m:] = 0
        out: list[Box] = []
        work = sal.copy()
        gmax = float(work.max())
        if gmax <= 1e-3:
            return out
        rad = int(sw * 0.12)
        for _ in range(self.max_boxes + 2):
            _, mv, _, loc = cv2.minMaxLoc(work)
            if mv < 0.3 * gmax:
                break
            px, py = loc
            region = (sal > 0.5 * mv).astype(np.uint8)
            n, lab, stats, _ = cv2.connectedComponentsWithStats(region)
            k = lab[py, px]
            x, y, w, h = stats[k][:4] if k > 0 else (px - sw * 0.04, py - sw * 0.04, sw * 0.08, sw * 0.08)
            w = float(np.clip(w * 1.15, sw * 0.06, sw * 0.2))
            h = float(np.clip(h * 1.15, sw * 0.05, sw * 0.2))
            out.append(Box(-1, (x + (stats[k][2] if k > 0 else w) / 2) * inv, (y + (stats[k][3] if k > 0 else h) / 2) * inv,
                           w * inv, h * inv, 0.5 + 2.0 * mv / gmax, "region"))
            cv2.circle(work, (px, py), rad, 0, -1)
        return out

    def _assoc(self, dets: list[Box]) -> None:
        used = set()
        for b in self.boxes:
            best, bd = None, 1e18
            for j, d in enumerate(dets):
                if j in used:
                    continue
                dist = math.hypot(b.cx - d.cx, b.cy - d.cy)
                if dist < bd:
                    best, bd = j, dist
            if best is not None and bd < 0.7 * max(b.w, b.h, dets[best].w, dets[best].h):
                d = dets[best]
                used.add(best)
                a = 0.55
                b.cx, b.cy = b.cx + (d.cx - b.cx) * a, b.cy + (d.cy - b.cy) * a
                b.w, b.h = b.w + (d.w - b.w) * 0.4, b.h + (d.h - b.h) * 0.4
                b.score, b.kind, b.miss = d.score, d.kind, 0
            else:
                b.miss += 1
        self.boxes = [b for b in self.boxes if b.miss < 3 and -0.1 * self.W < b.cx < 1.1 * self.W and -0.1 * self.H < b.cy < 1.1 * self.H]
        for j, d in enumerate(dets):
            if j in used or len(self.boxes) >= self.max_boxes:
                continue
            d.id = self._next_id
            self._next_id += 1
            self.boxes.append(d)

    def _flow(self, prev_gray: np.ndarray, gray: np.ndarray, scale: float) -> None:
        if not self.boxes:
            return
        p0 = np.array([[b.cx * scale, b.cy * scale] for b in self.boxes], np.float32).reshape(-1, 1, 2)
        p1, st, _ = cv2.calcOpticalFlowPyrLK(prev_gray, gray, p0, None, winSize=(21, 21), maxLevel=2)
        if p1 is None:
            return
        for b, q0, q1, s in zip(self.boxes, p0.reshape(-1, 2), p1.reshape(-1, 2), st.reshape(-1)):
            if s:
                d = (q1 - q0) / scale
                if abs(d[0]) < self.W * 0.15 and abs(d[1]) < self.H * 0.15:
                    b.cx += float(d[0])
                    b.cy += float(d[1])

    def _manual(self, t: float) -> None:
        pts = self.points
        if not pts:
            return
        pts = sorted(pts)
        if t <= pts[0][0]:
            q = pts[0]
        elif t >= pts[-1][0]:
            q = pts[-1]
        else:
            q = pts[-1]
            for a, b in zip(pts, pts[1:]):
                if a[0] <= t <= b[0]:
                    u = (t - a[0]) / max(b[0] - a[0], 1e-6)
                    q = [a[k] + (b[k] - a[k]) * u if k < len(a) and k < len(b) else (a[k] if k < len(a) else b[k])
                         for k in range(max(len(a), len(b)))]
                    break
        w = (q[3] if len(q) > 3 else 0.14) * self.W
        h = (q[4] if len(q) > 4 else 0.14) * self.W
        if not self.boxes:
            self.boxes = [Box(0, 0, 0, w, h, 5.0, "manual")]
        b = self.boxes[0]
        b.cx, b.cy, b.w, b.h = q[1] * self.W, q[2] * self.H, w, h
        self.target = b

    # ---- per frame
    def update(self, frame: np.ndarray, i: int, t: float) -> None:
        self.t = t
        dt = 1.0 / self.fps
        # schedule-driven levels
        lk, locked = 0.0, False
        for tl in self.lock_times:
            if tl <= t:
                a = t - tl
                lk = max(lk, 1.0 if a < 2.2 / 30 else math.exp(-(a - 2.2 / 30) / 0.11))
                if a < float(self.p.get("lock_hold", 0.4)):
                    locked = True
        self.lock, self.locked = lk, locked
        self.cut = max([math.exp(-(t - c) / 0.07) for c in self.p.get("cuts", []) if t >= c] or [0.0])
        ca = self.collapse_at
        if ca is not None and t >= float(ca):
            self.collapse = min(1.0, (t - float(ca)) / max(self.collapse_dur, 1e-3))
            self.collapse = self.collapse * self.collapse * (3 - 2 * self.collapse)
            ds = t - float(ca) - self.collapse_dur
            self.done = ds if ds >= 0 else -1.0
        else:
            self.collapse, self.done = 0.0, -1.0
        if self.provided:
            return
        if self.mode == "manual":
            self._manual(t)
        else:
            scale = min(1.0, self._small_w / self.W)
            gray = cv2.cvtColor(cv2.resize(frame, (int(self.W * scale), int(self.H * scale)), interpolation=cv2.INTER_AREA)
                                if scale < 1 else frame, cv2.COLOR_BGR2GRAY)
            if self._prev_gray is not None and self._prev_gray.shape == gray.shape:
                self._flow(self._prev_gray, gray, scale)
            if t - self._last_detect >= self.detect_every:
                self._last_detect = t
                self._assoc(self._detect(frame, gray, scale, self._prev_gray))
            self._prev_gray = gray
            for b in self.boxes:
                b.age += 1
            # sticky target: highest score·size, switch only after 0.3 s
            if self.boxes:
                cand = max(self.boxes, key=lambda b: b.score * (1.0 + 0.5 * math.sqrt(b.w * b.h) / self.W)
                           + (1.5 if self.target is b else 0.0))
                if self.target not in self.boxes:
                    self.target, self._tgt_since = cand, t
                elif cand is not self.target and t - self._tgt_since > 0.3:
                    self.target, self._tgt_since = cand, t
            else:
                self.target = None
        # focus follows the target with a short time-constant
        if self.target is not None:
            tx, ty = self.target.cx, self.target.cy
            if self.focus is None:
                self.focus = (tx, ty)
            else:
                k = 1 - math.exp(-dt / 0.12)
                self.focus = (self.focus[0] + (tx - self.focus[0]) * k, self.focus[1] + (ty - self.focus[1]) * k)

    def project(self, x: float, y: float) -> tuple[float, float]:
        """Frame pixel → output pixel through the lens camera (identity without lens_look)."""
        if self.cam is None:
            return x, y
        cam, rot, zoom, aim = self.cam
        o = cam.project(np.array([[x, y]]), rot, zoom, aim)[0]
        return float(o[0]), float(o[1])
