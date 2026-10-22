"""Contact sheets of shot keyframes — lets a multimodal coding agent "see" footage without a vision API."""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from .analyze.catalog import build_catalog
from .project import Project


def contact_sheets(project: Project, per_sheet: int = 20, cols: int = 4, thumb_w: int = 360) -> list[Path]:
    units = build_catalog(project, include_unusable=True)
    out_paths = []
    for n in range(0, len(units), per_sheet):
        chunk = units[n:n + per_sheet]
        tiles = []
        for u in chunk:
            kf = [project.root / k for k in u.get("keyframes", [])]
            img = None
            if kf and kf[0].exists():
                img = cv2.imdecode(np.fromfile(str(kf[0]), np.uint8), cv2.IMREAD_COLOR)
            if img is None:
                img = np.zeros((int(thumb_w * 9 / 16), thumb_w, 3), np.uint8)
            h = int(img.shape[0] * thumb_w / img.shape[1])
            img = cv2.resize(img, (thumb_w, h))
            box_h = int(thumb_w * 16 / 9) if h > thumb_w else int(thumb_w * 9 / 16)
            tile = np.zeros((box_h + 44, thumb_w, 3), np.uint8)
            tile[:min(h, box_h)] = img[:box_h]
            label = f"{u['uid']}  {u['start']:.1f}-{u['end']:.1f}s"
            cv2.putText(tile, label, (6, box_h + 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
            cv2.putText(tile, f"{u['category']} q={u['quality']:.2f} {u['device']}", (6, box_h + 38),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, (120, 220, 255), 1, cv2.LINE_AA)
            tiles.append(tile)
        th = max(t.shape[0] for t in tiles)
        tiles = [np.vstack([t, np.zeros((th - t.shape[0], thumb_w, 3), np.uint8)]) if t.shape[0] < th else t for t in tiles]
        while len(tiles) % cols:
            tiles.append(np.zeros_like(tiles[0]))
        rows = [np.hstack(tiles[i:i + cols]) for i in range(0, len(tiles), cols)]
        sheet = np.vstack(rows)
        p = project.analysis_dir / f"contact_{n // per_sheet + 1:02d}.jpg"
        ok_, buf = cv2.imencode(".jpg", sheet, [cv2.IMWRITE_JPEG_QUALITY, 85])
        buf.tofile(str(p))
        out_paths.append(p)
    return out_paths
