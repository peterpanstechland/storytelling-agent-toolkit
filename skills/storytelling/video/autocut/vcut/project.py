"""Project folder model: project.yaml + media registry."""
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import config
from .util import read_json, slugify, write_json

SUBDIRS = ["footage", "audio/voiceover", "audio/music", "assets", "analysis", "renders", "drafts"]

ASPECTS = {"16:9": (1920, 1080), "9:16": (1080, 1920), "1:1": (1080, 1080), "4:3": (1440, 1080), "3:4": (1080, 1440)}


def default_project_yaml(name: str, vtype: str, *, title: str | None = None, aspect: str | None = None,
                         style: str | None = None, duration: float | None = None,
                         platforms: list[str] | None = None) -> dict:
    t = config.get_type(vtype)
    d = t.get("defaults") or {}
    data: dict[str, Any] = {
        "name": name,
        "type": vtype,
        "type_name": t.get("name"),
        "title": title or name,
        "theme": "",
        "created": _dt.datetime.now().isoformat(timespec="seconds"),
        "target_duration": float(duration or d.get("duration", 60)),
        "aspect": aspect or d.get("aspect", "16:9"),
        "fps": 30,
        "platforms": platforms or list(d.get("platforms") or []),
        "style": style or d.get("style", "tech_minimal"),
        "language": "zh",
        "backend": "",  # 空 = 用全局设置（settings.yaml / VCUT_BACKEND）
        "voiceover": {"enabled": bool(t.get("voiceover", False)), "script": ""},
        "music": {"mood": [], "file": "", "volume": None, "beat_sync": None},
        "subtitles": True,
        "cta": "",
        "notes": "",
    }
    if vtype == "sponsored":
        data["sponsor"] = {
            "brand": "", "product": "", "campaign": "",
            "must_show": [], "key_messages": [], "forbidden": [],
            "logo": "", "logo_position": "top_right",
            "duration": None, "platform": [], "deadline": "", "cta": "", "hashtags": [], "notes": "",
        }
    if vtype in ("event", "sponsored"):
        data["event"] = {"name": "", "date": "", "location": ""}
    if vtype == "maker":
        data["maker"] = {"project_name": "", "features": [], "links": [], "bom_highlights": []}
    return data


@dataclass
class Project:
    root: Path

    # ---------- lifecycle ----------
    @classmethod
    def create(cls, name: str, vtype: str, parent: Path | None = None, **kw) -> "Project":
        parent = parent or config.projects_root()
        root = Path(parent) / slugify(name)
        if (root / "project.yaml").exists():
            raise FileExistsError(f"项目已存在：{root}")
        for sub in SUBDIRS:
            (root / sub).mkdir(parents=True, exist_ok=True)
        config.dump_yaml(default_project_yaml(name, vtype, **kw), root / "project.yaml")
        (root / "analysis" / "labels.yaml").write_text(
            "# 手动标注（优先级最高）。key 可以是 媒体ID、文件名 或 媒体ID#镜头序号\n"
            "# 例：\n# VID_20260101_120000_00_001.mp4: {category: pov, desc: 焊接主板, tags: [焊接]}\n"
            "# a1b2c3d4e5#3: {category: demo, highlight: 0.9}\n{}\n", encoding="utf-8")
        return cls(root)

    @classmethod
    def open(cls, ref: str | Path) -> "Project":
        p = Path(ref).expanduser()
        candidates = [p, config.projects_root() / str(ref), config.projects_root() / slugify(str(ref))]
        for c in candidates:
            if (c / "project.yaml").exists():
                return cls(c.resolve())
        raise FileNotFoundError(f"找不到项目：{ref}（在当前目录和 {config.projects_root()} 下都没有 project.yaml）")

    # ---------- paths ----------
    @property
    def yaml_path(self) -> Path:
        return self.root / "project.yaml"

    @property
    def analysis_dir(self) -> Path:
        return self.root / "analysis"

    @property
    def renders_dir(self) -> Path:
        return self.root / "renders"

    @property
    def drafts_dir(self) -> Path:
        return self.root / "drafts"

    @property
    def media_registry_path(self) -> Path:
        return self.root / "media.json"

    @property
    def edl_path(self) -> Path:
        return self.root / "edl.json"

    # ---------- data ----------
    def load(self) -> dict:
        return config.load_yaml(self.yaml_path) or {}

    def save(self, data: dict) -> None:
        config.dump_yaml(data, self.yaml_path)

    @property
    def data(self) -> dict:
        return self.load()

    def resolution(self) -> tuple[int, int]:
        aspect = str(self.data.get("aspect", "16:9"))
        return ASPECTS.get(aspect, ASPECTS["16:9"])

    def style(self) -> dict:
        return config.get_style(self.data.get("style"))

    def type_template(self) -> dict:
        return config.get_type(self.data.get("type", "vlog"))

    def media(self) -> list[dict]:
        return list((read_json(self.media_registry_path, {"media": []}) or {}).get("media", []))

    def save_media(self, items: list[dict]) -> None:
        write_json(self.media_registry_path, {"version": 1, "media": items})

    def media_path(self, item: dict) -> Path:
        p = Path(item["path"])
        return p if p.is_absolute() else (self.root / p)

    def labels(self) -> dict:
        p = self.analysis_dir / "labels.yaml"
        if not p.exists():
            return {}
        return config.load_yaml(p) or {}
