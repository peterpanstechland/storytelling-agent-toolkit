"""Merge media registry + cached analysis + manual labels into a flat shot catalog."""
from __future__ import annotations

import re
from pathlib import Path

from ..config import CATEGORIES
from ..project import Project
from ..util import read_json

FILENAME_HINTS: list[tuple[str, str]] = [
    (r"口播|talk|speak|讲解|intro", "talking_head"),
    (r"采访|interview", "interview"),
    (r"demo|演示", "demo"),
    (r"pov|第一视角", "pov"),
    (r"logo|品牌|brand", "logo"),
    (r"build|制作|焊|组装|assembl", "build"),
    (r"product|成品|产品|hero", "product"),
    (r"screen|录屏|代码|code", "screen"),
    (r"detail|特写|macro", "detail"),
    (r"selfie|自拍", "selfie"),
    (r"crowd|人群|现场", "crowd"),
    (r"空镜|风景|scenery|establish", "establishing"),
]

DEVICE_KIND_DEFAULT = {"360": "establishing", "pocket": "pov", "action": "action", "phone": "detail"}


def heuristic_category(media: dict, shot: dict) -> tuple[str, str]:
    name = media.get("source_name", "")
    for pat, cat in FILENAME_HINTS:
        if re.search(pat, name, re.I):
            return cat, f"文件名“{name}”"
    kind = (media.get("device") or {}).get("kind", "")
    if shot.get("speech_ratio", 0) >= 0.45:
        return ("selfie" if kind == "360" else "talking_head"), "检测到持续说话"
    if not shot.get("_has_transcript") and kind == "phone" and shot.get("audio_activity", 0) >= 0.6:
        return "talking_head", "手机素材持续有声（未做语音转写，推测为口播）"
    if kind in DEVICE_KIND_DEFAULT:
        return DEVICE_KIND_DEFAULT[kind], f"设备类型 {kind}"
    return "broll", "默认"


def _label_for(labels: dict, media: dict, shot_idx: int) -> dict:
    keys_media = [media["id"], media.get("source_name", ""), Path(media.get("path", "")).name, Path(media.get("source_name", "")).stem]
    merged: dict = {}
    for k in keys_media:
        if k and isinstance(labels.get(k), dict):
            merged.update(labels[k])
    for k in keys_media:
        if k and isinstance(labels.get(f"{k}#{shot_idx}"), dict):
            merged.update(labels[f"{k}#{shot_idx}"])
    return merged


def build_catalog(project: Project, include_unusable: bool = False) -> list[dict]:
    labels = project.labels()
    units: list[dict] = []
    media_items = [m for m in project.media() if m["kind"] == "video" and not m.get("needs_export")]
    for m in media_items:
        data = read_json(project.analysis_dir / f"{m['id']}.json")
        if not data:
            continue
        segs = (data.get("transcript") or {}).get("segments") or []
        for s in data.get("shots", []):
            lab = _label_for(labels, m, s["idx"])
            if lab.get("skip"):
                continue
            vis = s.get("vision") or {}
            if lab.get("category") in CATEGORIES:
                cat, src = lab["category"], "label"
            elif vis.get("category"):
                cat, src = vis["category"], "vision"
            else:
                cat, src = heuristic_category(m, {**s, "_has_transcript": bool(segs) or bool((data.get("stages") or {}).get("transcript"))})
            q = (s.get("quality") or {}).get("score", 0.5)
            usable = vis.get("usable", True) if not lab.get("keep") else True
            if not usable and not include_unusable:
                continue
            highlight = float(lab.get("highlight", vis.get("highlight", 0.4 + 0.4 * q)))
            units.append({
                "uid": f"{m['id']}#{s['idx']}",
                "media_id": m["id"],
                "path": m["path"],
                "source_name": m.get("source_name"),
                "device": (m.get("device") or {}).get("id", "unknown"),
                "device_kind": (m.get("device") or {}).get("kind", ""),
                "creation_time": (m.get("probe") or {}).get("creation_time", ""),
                "media_duration": float(data.get("duration") or 0),
                "has_audio": bool((m.get("probe") or {}).get("has_audio")),
                "idx": s["idx"],
                "start": s["start"],
                "end": s["end"],
                "duration": round(s["end"] - s["start"], 3),
                "category": cat,
                "category_source": src,
                "description": lab.get("desc") or vis.get("description") or "",
                "tags": list(lab.get("tags") or []) + list(vis.get("tags") or []),
                "text_in_frame": vis.get("text_in_frame", ""),
                "highlight": round(highlight, 3),
                "quality": q,
                "quality_notes": (s.get("quality") or {}).get("notes", []),
                "speech_ratio": s.get("speech_ratio", 0.0),
                "audio_activity": s.get("audio_activity", 0.0),
                "speech": s.get("speech", ""),
                "segments": [x for x in segs if x["end"] > s["start"] and x["start"] < s["end"]],
                "keyframes": s.get("keyframes", []),
                "projection": m.get("projection", "flat"),
                "activity": s.get("activity", 0.0),
                "peak_t": s.get("peak_t", round((s["start"] + s["end"]) / 2, 3)),
                "motion": (s.get("quality") or {}).get("motion", 0.0),
                "pinned": bool(lab.get("keep")),
            })
    units.sort(key=lambda u: (u["creation_time"] or "", u["source_name"] or "", u["start"]))
    for i, u in enumerate(units):
        u["order"] = i
    return units


def transcript_units(project: Project) -> list[dict]:
    """Sentence-level units from transcripts (for 口播 sections)."""
    out = []
    labels = project.labels()
    for m in project.media():
        if m["kind"] != "video" or m.get("needs_export"):
            continue
        data = read_json(project.analysis_dir / f"{m['id']}.json")
        if not data:
            continue
        lab = _label_for(labels, m, -1)
        if lab.get("skip"):
            continue
        for i, seg in enumerate((data.get("transcript") or {}).get("segments") or []):
            if seg.get("no_speech_prob", 0) > 0.8:
                continue
            out.append({"uid": f"{m['id']}@{i}", "media_id": m["id"], "path": m["path"],
                        "source_name": m.get("source_name"), "start": seg["start"], "end": seg["end"],
                        "text": seg["text"], "media_duration": float(data.get("duration") or 0),
                        "creation_time": (m.get("probe") or {}).get("creation_time", ""),
                        "device_kind": (m.get("device") or {}).get("kind", "")})
    out.sort(key=lambda u: (u["creation_time"] or "", u["source_name"] or "", u["start"]))
    return out
