"""Device detection driven by config/devices.yaml (never hard-coded)."""
from __future__ import annotations

import re
from pathlib import Path

from . import config
from .media import ProbeInfo

_TAG_KEYS_HINT = ("make", "model", "manufacturer", "encoder", "handler", "comment", "description",
                  "com.android", "com.apple", "camera", "device", "software", "title")


def _tag_blob(tags: dict[str, str]) -> str:
    parts = []
    for k, v in tags.items():
        kl = k.lower()
        if any(h in kl for h in _TAG_KEYS_HINT) or len(str(v)) < 80:
            parts.append(f"{k}={v}")
    return " | ".join(parts).lower()


def detect_device(path: Path, probe: ProbeInfo | None = None, device_list: list[dict] | None = None) -> dict:
    """Return {id, label, kind, score, reasons} (id='unknown' when nothing matches)."""
    devs = device_list if device_list is not None else config.devices()
    name = Path(path).name
    ext = Path(path).suffix.lower()
    blob = _tag_blob(probe.tags) if probe else ""
    best = {"id": "unknown", "label": "未知设备", "kind": "", "score": 0, "reasons": []}
    for d in devs:
        m = d.get("match") or {}
        score, reasons = 0, []
        for kw in m.get("tags") or []:
            if kw and kw.lower() in blob:
                score += 5
                reasons.append(f"元数据含“{kw}”")
                break
        for kw in m.get("make") or []:
            if kw and kw.lower() in blob:
                score += 2
                reasons.append(f"厂商“{kw}”")
                break
        for pat in m.get("filename") or []:
            try:
                if re.search(pat, name, re.I):
                    score += 3
                    reasons.append("文件名规则")
                    break
            except re.error:
                continue
        res = f"{getattr(probe, 'width', 0)}x{getattr(probe, 'height', 0)}" if probe else ""
        if res and res in [str(r).lower() for r in (m.get("resolution") or [])] and score > 0:
            score += 2
            reasons.append(f"分辨率 {res}")
        if ext and ext in [e.lower() for e in (m.get("ext") or [])]:
            score += 4
            reasons.append(f"扩展名 {ext}")
        if score > best["score"]:
            best = {"id": d["id"], "label": d.get("label", d["id"]), "kind": str(d.get("kind", "")),
                    "score": score, "reasons": reasons}
    best["confidence"] = "high" if best["score"] >= 5 else ("medium" if best["score"] >= 3 else "low")
    return best


def available_devices(kinds: list[str] | None = None) -> list[dict]:
    out = []
    for d in config.devices():
        if not d.get("available", True):
            continue
        if kinds and str(d.get("kind")) not in [str(k) for k in kinds]:
            continue
        out.append(d)
    return out


def device_labels_for(kinds: list[str]) -> list[str]:
    """Kinds in preference order -> available device labels (deduped, ordered)."""
    labels: list[str] = []
    for k in kinds:
        for d in available_devices([k]):
            if d.get("label") not in labels:
                labels.append(d.get("label"))
    return labels
