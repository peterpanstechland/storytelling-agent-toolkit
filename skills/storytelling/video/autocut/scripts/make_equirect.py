"""Synthetic 2:1 equirectangular test clip (no real 360 camera needed).

Horizon markers make every reframe visibly verifiable:
  yaw   0° → red pillar   "0 N"      yaw  90° → green pillar "90 E"
  yaw 180° → blue pillar  "180 S"    yaw -90° → yellow pillar "270 W"
plus a 30° grid, a sun at (yaw 45°, pitch 55°), a checkered ground (great for tiny-planet), and a magenta
"walker" that circles the horizon (yaw = 20° + 18°/s) so subject-follow can be checked.
"""
from __future__ import annotations

import math
import shutil
import subprocess
from pathlib import Path

import cv2
import numpy as np

FF = shutil.which("ffmpeg") or "ffmpeg"


def _x(yaw: float, W: int) -> int:
    return int(round(((yaw + 180.0) % 360.0) / 360.0 * W))


def _y(pitch: float, H: int) -> int:
    return int(round((90.0 - pitch) / 180.0 * H))


def background(W: int, H: int) -> np.ndarray:
    lat = 90.0 - (np.arange(H) + 0.5) / H * 180.0
    lon = (np.arange(W) + 0.5) / W * 360.0 - 180.0
    LON, LAT = np.meshgrid(lon, lat)
    img = np.zeros((H, W, 3), np.float32)
    sky = LAT >= 0
    t = np.clip(LAT / 90.0, 0, 1)
    for c, (lo, hi) in enumerate([(235, 120), (200, 60), (140, 20)]):  # BGR: light horizon → deep blue zenith
        img[..., c] = np.where(sky, lo + (hi - lo) * t, 0)
    cell = ((np.floor(LON / 15.0) + np.floor(LAT / 10.0)) % 2).astype(np.float32)
    ground = ~sky
    img[..., 0] = np.where(ground, 40 + 30 * cell, img[..., 0])
    img[..., 1] = np.where(ground, 110 + 60 * cell, img[..., 1])
    img[..., 2] = np.where(ground, 50 + 30 * cell, img[..., 2])
    img = img.astype(np.uint8)
    # grid every 30° (thin), horizon line
    for a in range(-180, 180, 30):
        cv2.line(img, (_x(a, W), _y(30, H)), (_x(a, W), _y(-30, H)), (255, 255, 255), max(1, W // 1500))
    cv2.line(img, (0, _y(0, H)), (W, _y(0, H)), (255, 255, 255), max(2, W // 900))
    # sun
    cv2.circle(img, (_x(45, W), _y(55, H)), int(H * 0.035), (60, 230, 255), -1, cv2.LINE_AA)
    # trees (triangles) on the horizon
    for a in (-150, -120, -60, -30, 30, 60, 120, 150):
        x, y0 = _x(a, W), _y(0, H)
        s = int(H * 0.04)
        pts = np.array([[x - s // 2, y0], [x + s // 2, y0], [x, y0 - int(s * 1.6)]], np.int32)
        cv2.fillPoly(img, [pts], (40, 120, 30), cv2.LINE_AA)
    # cardinal pillars with labels
    marks = [(0, (40, 40, 230), "0 N"), (90, (60, 200, 60), "90 E"), (180, (220, 90, 40), "180 S"), (-90, (40, 220, 240), "270 W")]
    for a, col, label in marks:
        x0, x1 = _x(a - 5, W), _x(a + 5, W)
        y0, y1 = _y(26, H), _y(-12, H)
        if x1 < x0:  # wraps at ±180
            cv2.rectangle(img, (x0, y0), (W, y1), col, -1)
            cv2.rectangle(img, (0, y0), (x1, y1), col, -1)
            cx = 0
        else:
            cv2.rectangle(img, (x0, y0), (x1, y1), col, -1)
            cx = (x0 + x1) // 2
        fs = H / 900
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_DUPLEX, fs, max(2, int(fs * 2)))
        for xx in ([cx, W] if cx == 0 else [cx]):  # draw on both edges when wrapping
            cv2.putText(img, label, (xx - tw // 2, (y0 + y1) // 2 + th // 2), cv2.FONT_HERSHEY_DUPLEX, fs,
                        (255, 255, 255), max(2, int(fs * 2)), cv2.LINE_AA)
    return img


def walker_yaw(t: float) -> float:
    return 20.0 + 18.0 * t


def draw_walker(img: np.ndarray, t: float) -> None:
    H, W = img.shape[:2]
    a = walker_yaw(t)
    bob = 0.6 * math.sin(t * 2 * math.pi * 1.5)
    x = _x(a, W)
    yb0, yb1 = _y(9 + bob, H), _y(-6 + bob, H)
    bw = max(4, int(W * 4.0 / 360.0) // 2)
    cv2.rectangle(img, (x - bw, yb0), (x + bw, yb1), (200, 40, 220), -1)
    cv2.circle(img, (x, _y(12 + bob, H)), int(bw * 0.9), (180, 200, 255), -1, cv2.LINE_AA)
    swing = int(bw * 0.8 * math.sin(t * 2 * math.pi * 1.5))
    cv2.line(img, (x - bw // 2, yb1), (x - bw // 2 - swing, _y(-12, H)), (90, 20, 120), max(2, bw // 3))
    cv2.line(img, (x + bw // 2, yb1), (x + bw // 2 + swing, _y(-12, H)), (90, 20, 120), max(2, bw // 3))


def make_equirect(path: Path, W: int = 2880, dur: float = 12.0, fps: int = 30) -> Path:
    H = W // 2
    bg = background(W, H)
    path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [FF, "-hide_banner", "-loglevel", "error", "-y",
           "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}", "-r", str(fps), "-i", "-",
           "-f", "lavfi", "-t", f"{dur}", "-i", "anoisesrc=c=brown:a=0.05,lowpass=f=600",
           "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-preset", "veryfast", "-crf", "24", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "96k", "-shortest", "-metadata", "comment=Insta360 X5 equirectangular export (synthetic)",
           str(path)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    n = int(round(dur * fps))
    for i in range(n):
        f = bg.copy()
        draw_walker(f, i / fps)
        proc.stdin.write(f.tobytes())  # type: ignore[union-attr]
    proc.stdin.close()  # type: ignore[union-attr]
    if proc.wait() != 0:
        raise SystemExit("ffmpeg failed while writing equirect test clip")
    return path


if __name__ == "__main__":
    import sys
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "equirect_test.mp4")
    make_equirect(out, W=int(sys.argv[2]) if len(sys.argv) > 2 else 2880)
    print(out)
