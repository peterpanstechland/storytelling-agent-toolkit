"""Lightweight subject detection + tracking (for 360 follow / hero and 9:16 subject-aware reframing).

Detector chain (first that is available wins, `track.detector` in settings.yaml can force one):
  yolo   person boxes from a YOLOv8/YOLO11 ONNX file (track.yolo_model) via onnxruntime (extra `track`) or cv2.dnn
  yunet  OpenCV FaceDetectorYN with face_detection_yunet_2023mar.onnx (`autocut models fetch yunet`)
  haar   Haar face cascade + HOG people (only in OpenCV 4.x builds; OpenCV 5 dropped them)
  motion foreground vs. temporal-median background (static camera; also what the synthetic tests use)
Results are smoothed (Gaussian + slew-rate limit) so the virtual camera never jerks.
"""
from __future__ import annotations

import math
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import cv2

try:  # silence OpenCV 5 DNN 'setPreferableTarget' warnings from YuNet
    cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_ERROR)
except Exception:  # noqa: BLE001
    try:
        cv2.setLogLevel(2)
    except Exception:  # noqa: BLE001
        pass
import numpy as np

from .. import config
from ..media import ffmpeg_bin
from .ease import smooth_series
from .sphere import Reprojector, View, view_point_to_angles

YUNET_URL = ("https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/face_detection_yunet/"
             "face_detection_yunet_2023mar.onnx")


@dataclass
class Det:
    x: float
    y: float
    w: float
    h: float
    score: float
    kind: str = "person"

    @property
    def cx(self) -> float:
        return self.x + self.w / 2

    @property
    def cy(self) -> float:
        return self.y + self.h / 2


def models_dir() -> Path:
    base = os.environ.get("VCUT_MODELS_DIR")
    if base:
        return Path(base)
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", Path.home())) / "vcut" / "models"
    return Path.home() / ".cache" / "vcut" / "models"


def _tcfg() -> dict:
    return config.settings().get("track") or {}


def yunet_path() -> Path | None:
    p = _tcfg().get("yunet_model") or ""
    cands = [Path(p)] if p else []
    cands.append(models_dir() / "face_detection_yunet_2023mar.onnx")
    return next((c for c in cands if c.is_file() and c.stat().st_size > 10_000), None)


def fetch_yunet() -> Path:
    import httpx
    out = models_dir() / "face_detection_yunet_2023mar.onnx"
    out.parent.mkdir(parents=True, exist_ok=True)
    with httpx.stream("GET", os.environ.get("VCUT_YUNET_URL") or YUNET_URL, follow_redirects=True, timeout=60) as r:
        r.raise_for_status()
        with open(out, "wb") as f:
            for chunk in r.iter_bytes():
                f.write(chunk)
    if out.stat().st_size < 10_000:
        raise RuntimeError("下载的 YuNet 模型文件不完整")
    return out


class Detector:
    """Callable: img(BGR) → list[Det]."""

    def __init__(self, prefer: str | None = None):
        prefer = (prefer or _tcfg().get("detector") or "auto").lower()
        self.conf = float(_tcfg().get("conf", 0.45))
        self.kind = "none"
        self._yolo = self._yunet = None
        self._haar = self._hog = None
        order = ["yolo", "yunet", "haar", "motion"] if prefer == "auto" else [prefer]
        for k in order:
            if k == "yolo" and self._init_yolo():
                self.kind = "yolo"
                break
            if k == "yunet" and self._init_yunet():
                self.kind = "yunet"
                break
            if k == "haar" and self._init_haar():
                self.kind = "haar"
                break
            if k == "motion":
                self.kind = "motion"
                break

    # ---- backends
    def _init_yolo(self) -> bool:
        path = _tcfg().get("yolo_model") or ""
        if not path or not Path(path).is_file():
            return False
        try:
            import onnxruntime as ort  # type: ignore
            prov = [p for p in ("CUDAExecutionProvider", "CPUExecutionProvider") if p in ort.get_available_providers()]
            self._yolo = ("ort", ort.InferenceSession(path, providers=prov))
        except Exception:  # noqa: BLE001 - fall back to OpenCV DNN
            try:
                self._yolo = ("cv", cv2.dnn.readNetFromONNX(path))
            except Exception:  # noqa: BLE001
                return False
        return True

    def _init_yunet(self) -> bool:
        p = yunet_path()
        if not p or not hasattr(cv2, "FaceDetectorYN"):
            return False
        try:
            self._yunet = cv2.FaceDetectorYN.create(str(p), "", (320, 320), self.conf, 0.3, 50)
            return True
        except Exception:  # noqa: BLE001
            return False

    def _init_haar(self) -> bool:
        """Haar faces + HOG people exist in OpenCV 4.x only (removed from the OpenCV 5 main module)."""
        if not hasattr(cv2, "CascadeClassifier") and not hasattr(cv2, "HOGDescriptor"):
            return False
        try:
            xml = Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml"
            self._haar = cv2.CascadeClassifier(str(xml)) if xml.exists() else None
        except Exception:  # noqa: BLE001
            self._haar = None
        if hasattr(cv2, "HOGDescriptor"):
            self._hog = cv2.HOGDescriptor()
            self._hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())
        return self._haar is not None or self._hog is not None

    def __call__(self, img: np.ndarray) -> list[Det]:
        if self.kind == "yolo":
            return self._run_yolo(img)
        if self.kind == "yunet":
            h, w = img.shape[:2]
            self._yunet.setInputSize((w, h))  # type: ignore[union-attr]
            _, faces = self._yunet.detect(img)  # type: ignore[union-attr]
            out = []
            for f in (faces if faces is not None else []):
                x, y, fw, fh, sc = float(f[0]), float(f[1]), float(f[2]), float(f[3]), float(f[-1])
                out.append(Det(x, y, fw, fh * 1.0, sc, "face"))
            return out
        if self.kind == "haar":
            out: list[Det] = []
            g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            if self._haar is not None and not self._haar.empty():
                for (x, y, w, h) in self._haar.detectMultiScale(g, 1.15, 5, minSize=(24, 24)):
                    out.append(Det(float(x), float(y), float(w), float(h), 0.6, "face"))
            if not out and self._hog is not None:
                rects, weights = self._hog.detectMultiScale(img, winStride=(8, 8), padding=(8, 8), scale=1.08)
                for (x, y, w, h), sc in zip(rects, np.ravel(weights) if len(weights) else []):
                    if sc > 0.5:
                        out.append(Det(float(x), float(y), float(w), float(h), float(min(1.0, sc / 2)), "person"))
            return out
        return []

    def _run_yolo(self, img: np.ndarray) -> list[Det]:
        h, w = img.shape[:2]
        S = 640
        r = min(S / w, S / h)
        nw, nh = int(w * r), int(h * r)
        canvas = np.full((S, S, 3), 114, np.uint8)
        canvas[:nh, :nw] = cv2.resize(img, (nw, nh))
        blob = cv2.dnn.blobFromImage(canvas, 1 / 255.0, (S, S), swapRB=True)
        kind, net = self._yolo  # type: ignore[misc]
        if kind == "ort":
            pred = net.run(None, {net.get_inputs()[0].name: blob})[0]
        else:
            net.setInput(blob)
            pred = net.forward()
        pred = np.squeeze(pred)
        if pred.shape[0] < pred.shape[1]:
            pred = pred.T  # (N, 4+classes)
        scores = pred[:, 4]  # class 0 = person
        keep = scores > self.conf
        boxes, sc = pred[keep, :4], scores[keep]
        rects = [[float((cx - bw / 2) / r), float((cy - bh / 2) / r), float(bw / r), float(bh / r)] for cx, cy, bw, bh in boxes]
        idx = cv2.dnn.NMSBoxes(rects, sc.tolist(), self.conf, 0.45) if rects else []
        return [Det(*rects[i], float(sc[i]), "person") for i in np.ravel(idx)]


# ------------------------------------------------------------------ sampling helpers
def sample_frames(path: Path, start: float, dur: float, fps: float, width: int, height: int) -> list[tuple[float, np.ndarray]]:
    cmd = [ffmpeg_bin(), "-hide_banner", "-nostdin", "-v", "error", "-ss", f"{start:.3f}", "-t", f"{dur:.3f}", "-i", str(path),
           "-vf", f"fps={fps},scale={width}:{height}", "-f", "rawvideo", "-pix_fmt", "bgr24", "pipe:1"]
    kw = {"creationflags": 0x08000000} if os.name == "nt" else {}
    raw = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False, **kw).stdout
    n = width * height * 3
    return [(k / fps, np.frombuffer(raw[k * n:(k + 1) * n], np.uint8).reshape(height, width, 3))
            for k in range(len(raw) // n)]


def _motion_blobs(frames: list[np.ndarray]) -> list[tuple[float, float, float] | None]:
    """Per frame: (x, y, area_frac) of the dominant moving blob vs. the temporal median, or None."""
    if len(frames) < 3:
        return [None] * len(frames)
    grays = [cv2.GaussianBlur(cv2.cvtColor(f, cv2.COLOR_BGR2GRAY), (5, 5), 0) for f in frames]
    bg = np.median(np.stack(grays[:: max(1, len(grays) // 15)]), axis=0).astype(np.uint8)
    out: list[tuple[float, float, float] | None] = []
    kernel = np.ones((5, 5), np.uint8)
    for g in grays:
        m = (cv2.absdiff(g, bg) > 28).astype(np.uint8)
        frac = float(m.mean())
        if frac > 0.25 or frac < 0.0005:  # camera moving / nothing moving
            out.append(None)
            continue
        m = cv2.dilate(cv2.morphologyEx(m, cv2.MORPH_OPEN, kernel), kernel, iterations=2)
        n, _lab, stats, cents = cv2.connectedComponentsWithStats(m)
        if n <= 1:
            out.append(None)
            continue
        k = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
        out.append((float(cents[k][0]), float(cents[k][1]), float(stats[k, cv2.CC_STAT_AREA]) / m.size))
    return out


def _ang(a: float, b: float) -> float:
    return abs((a - b + 180) % 360 - 180)


# ------------------------------------------------------------------ 360
def track_360(path: Path, start: float, dur: float, *, sample_fps: float | None = None, detector: str | None = None,
              initial_yaw: float | None = None) -> dict:
    """Subject heading over time on an equirect clip → {"track": [[t, yaw, pitch]], "method": str}."""
    sample_fps = float(sample_fps or min(3.0, float(_tcfg().get("sample_fps", 2.0))))
    frames = sample_frames(path, start, dur, sample_fps, 1440, 720)
    if not frames:
        return {"track": [], "method": "none"}
    det = Detector(detector)
    obs: list[tuple[float, float, float, float] | None] = []  # (t, yaw, pitch, weight)
    if det.kind not in ("none", "motion"):
        vw, vh = 640, 480
        R = Reprojector(vw, vh, 1440, 720)
        heads = [View(y, -5.0, 0.0, 100.0) for y in (0, 90, 180, -90)]
        prev_yaw = initial_yaw
        for t, f in frames:
            cands = []
            for v in heads:
                for d in det(R.render(f, v)):
                    yaw, pitch = view_point_to_angles(d.cx, d.cy, v, vw, vh)
                    cands.append((yaw, pitch, d.score * math.sqrt(d.w * d.h)))
            if cands:
                if prev_yaw is not None:
                    best = min(cands, key=lambda c: _ang(c[0], prev_yaw) - 0.5 * c[2])
                else:
                    best = max(cands, key=lambda c: c[2])
                prev_yaw = best[0]
                obs.append((t, best[0], best[1], best[2]))
            else:
                obs.append(None)
    method = det.kind
    if det.kind in ("none", "motion") or sum(o is not None for o in obs) < max(2, len(frames) // 4):
        blobs = _motion_blobs([f for _, f in frames])
        mobs = []
        for (t, _f), b in zip(frames, blobs):
            if b is None:
                mobs.append(None)
            else:
                yaw = (b[0] + 0.5) / 1440 * 360 - 180
                pitch = 90 - (b[1] + 0.5) / 720 * 180
                mobs.append((t, yaw, pitch, b[2]))
        if sum(o is not None for o in mobs) >= max(2, len(frames) // 4):
            obs, method = mobs, "motion"
    pts = [o for o in obs if o is not None]
    if not pts:
        y0 = initial_yaw if initial_yaw is not None else 0.0
        return {"track": [[0.0, y0, -4.0], [dur, y0, -4.0]], "method": "fixed"}
    ts = [p[0] for p in pts]
    yaws = smooth_series([p[1] for p in pts], ts, sigma_s=0.5, max_rate=float(_tcfg().get("max_slew_deg", 90.0)), circular=True)
    pitches = smooth_series([max(-30.0, min(20.0, p[2])) for p in pts], ts, sigma_s=0.8, max_rate=40.0)
    tr = [[round(t, 3), round(float(y), 2), round(float(p), 2)] for t, y, p in zip(ts, yaws, pitches)]
    if tr[0][0] > 0:
        tr.insert(0, [0.0, tr[0][1], tr[0][2]])
    if tr[-1][0] < dur:
        tr.append([round(dur, 3), tr[-1][1], tr[-1][2]])
    return {"track": tr, "method": method}


# ------------------------------------------------------------------ flat
def track_flat(path: Path, start: float, dur: float, src_w: int, src_h: int, *, sample_fps: float | None = None,
               detector: str | None = None) -> dict:
    """Subject centre over time (normalized 0..1) on flat footage → {"track": [[t, x, y]], "method": str}."""
    sample_fps = float(sample_fps or _tcfg().get("sample_fps", 3.0))
    aw = 640
    ah = max(2, int(round(aw * src_h / max(1, src_w) / 2)) * 2)
    frames = sample_frames(path, start, dur, sample_fps, aw, ah)
    if not frames:
        return {"track": [], "method": "none"}
    det = Detector(detector)
    obs = []
    prev = None
    if det.kind not in ("none", "motion"):
        for t, f in frames:
            ds = det(f)
            if ds:
                if prev is not None:
                    d = min(ds, key=lambda d: math.hypot(d.cx / aw - prev[0], d.cy / ah - prev[1]) - 0.002 * math.sqrt(d.w * d.h))
                else:
                    d = max(ds, key=lambda d: d.score * d.w * d.h)
                # faces: frame a bit below the face centre (head room); persons: upper third
                yy = (d.cy + 0.6 * d.h) / ah if d.kind == "face" else (d.y + 0.35 * d.h) / ah
                prev = (d.cx / aw, yy)
                obs.append((t, prev[0], prev[1]))
    method = det.kind
    if len(obs) < max(2, len(frames) // 4):
        blobs = _motion_blobs([f for _, f in frames])
        mobs = [(t, b[0] / aw, b[1] / ah) for (t, _), b in zip(frames, blobs) if b is not None]
        if len(mobs) >= max(2, len(frames) // 4):
            obs, method = mobs, "motion"
    if not obs:
        return {"track": [], "method": "none"}
    ts = [o[0] for o in obs]
    xs = smooth_series([o[1] for o in obs], ts, sigma_s=0.7, max_rate=0.35)
    ys = smooth_series([o[2] for o in obs], ts, sigma_s=0.9, max_rate=0.25)
    tr = [[round(t, 3), round(float(x), 4), round(float(y), 4)] for t, x, y in zip(ts, xs, ys)]
    if tr[0][0] > 0:
        tr.insert(0, [0.0, tr[0][1], tr[0][2]])
    if tr[-1][0] < dur:
        tr.append([round(dur, 3), tr[-1][1], tr[-1][2]])
    return {"track": tr, "method": method}
