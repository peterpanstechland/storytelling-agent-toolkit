"""Settings / config-file loading.

Lookup order for the config directory (devices.yaml, settings.yaml, styles/, types/):
  1. $VCUT_CONFIG_DIR
  2. <autocut>/config  (next to this package; the normal case inside the storytelling skill)
  3. <package>/_config (optional bundled copy)
Environment variables always win over settings.yaml.
"""
from __future__ import annotations

import copy
import os
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

PKG_DIR = Path(__file__).resolve().parent
REPO_DIR = PKG_DIR.parent  # the autocut/ folder that holds vcut/ and config/

CATEGORIES: dict[str, str] = {
    "talking_head": "口播/对镜头讲话",
    "interview": "采访/对话",
    "selfie": "自拍随拍",
    "establishing": "环境/建立镜头",
    "crowd": "现场氛围/人群",
    "pov": "第一视角/手部操作",
    "build": "制作过程",
    "detail": "特写/细节",
    "product": "产品/成品展示",
    "demo": "功能演示",
    "screen": "屏幕/软件界面",
    "logo": "品牌/Logo/主视觉",
    "action": "运动/动态",
    "broll": "其他空镜",
}


def config_dir() -> Path:
    env = os.environ.get("VCUT_CONFIG_DIR")
    if env:
        return Path(env).expanduser()
    repo_cfg = REPO_DIR / "config"
    if (repo_cfg / "settings.yaml").exists():
        return repo_cfg
    return PKG_DIR / "_config"


def load_yaml(path: Path) -> Any:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def dump_yaml(data: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False, width=120)


def deep_merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


@lru_cache(maxsize=1)
def settings() -> dict:
    data = load_yaml(config_dir() / "settings.yaml") or {}
    # optional per-user override file (not committed)
    local = config_dir() / "settings.local.yaml"
    if local.exists():
        data = deep_merge(data, load_yaml(local) or {})
    if os.environ.get("VCUT_BACKEND"):
        data["backend"] = os.environ["VCUT_BACKEND"]
    if os.environ.get("VCUT_PROJECTS_ROOT"):
        data["projects_root"] = os.environ["VCUT_PROJECTS_ROOT"]
    if os.environ.get("VCUT_MUSIC_LIBRARY"):
        data.setdefault("music", {})["library"] = os.environ["VCUT_MUSIC_LIBRARY"]
    if os.environ.get("VCUT_JIANYING_DRAFTS"):
        data.setdefault("jianying", {})["drafts_dir"] = os.environ["VCUT_JIANYING_DRAFTS"]
    return data


def projects_root() -> Path:
    root = settings().get("projects_root") or ""
    if root:
        return Path(root).expanduser()
    return Path.home() / "Videos" / "vcut-projects"


def jianying_drafts_dir() -> Path | None:
    d = (settings().get("jianying") or {}).get("drafts_dir") or ""
    if d:
        return Path(d).expanduser()
    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA")
        if local:
            return Path(local) / "JianyingPro" / "User Data" / "Projects" / "com.lveditor.draft"
    return None


@lru_cache(maxsize=1)
def devices() -> list[dict]:
    data = load_yaml(config_dir() / "devices.yaml") or {}
    return list(data.get("devices") or [])


def _load_dir(sub: str) -> dict[str, dict]:
    out: dict[str, dict] = {}
    d = config_dir() / sub
    if d.is_dir():
        for p in sorted(d.glob("*.yaml")):
            item = load_yaml(p) or {}
            item.setdefault("id", p.stem)
            out[item["id"]] = item
    return out


@lru_cache(maxsize=1)
def styles() -> dict[str, dict]:
    return _load_dir("styles")


@lru_cache(maxsize=1)
def type_templates() -> dict[str, dict]:
    return _load_dir("types")


def get_style(name: str | None) -> dict:
    all_styles = styles()
    if not name:
        return all_styles["tech_minimal"]
    if name in all_styles:
        return all_styles[name]
    for s in all_styles.values():
        if name == s.get("name") or name in (s.get("aliases") or []):
            return s
    choices = ", ".join(f"{k}({v.get('name')})" for k, v in all_styles.items())
    raise KeyError(f"未知风格：{name}。可选：{choices}")


def get_type(name: str) -> dict:
    t = type_templates()
    if name not in t:
        raise KeyError(f"未知视频类型：{name}。可选：{', '.join(t)}")
    return t[name]
