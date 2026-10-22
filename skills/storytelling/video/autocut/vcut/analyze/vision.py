"""Per-shot visual understanding through a pluggable backend."""
from __future__ import annotations

from pathlib import Path

from ..backends.base import Backend
from ..config import CATEGORIES

SYSTEM = ("你是一名专业视频剪辑助理，帮创作者理解素材。只根据画面和给出的文字判断，不要编造。"
          "所有描述用简体中文，简洁具体（谁/什么/在做什么/镜头类型）。")


def _cat_list() -> str:
    return "\n".join(f"- {k}: {v}" for k, v in CATEGORIES.items())


def build_prompt(project: dict, media: dict, shots: list[dict]) -> str:
    lines = [
        f"项目类型：{project.get('type_name') or project.get('type')}；标题：{project.get('title')}；主题：{project.get('theme') or '未填写'}",
        f"拍摄设备：{media.get('device', {}).get('label', '未知')}；文件：{media.get('source_name')}",
        "下面按顺序给出若干镜头，每个镜头附 1~2 张关键帧（图片按镜头顺序排列）。",
    ]
    for s in shots:
        t = f"镜头 idx={s['idx']}：{s['start']:.1f}s~{s['end']:.1f}s，图片 {s.get('_n_images', 1)} 张"
        if s.get("_speech"):
            t += f"；这段的语音转写：“{s['_speech'][:120]}”"
        lines.append(t)
    lines += [
        "\n镜头类别（category 只能从下面选一个）：",
        _cat_list(),
        "\n输出 JSON：{\"shots\": [{\"idx\": 整数, \"category\": 类别, \"description\": 一句话描述,"
        " \"tags\": [3~6 个中文关键词], \"subjects\": [主体], \"highlight\": 0~1 的精彩程度,"
        " \"usable\": true/false, \"issues\": 画面问题(没有则空字符串), \"text_in_frame\": 画面里能看清的文字/品牌名}]}",
    ]
    return "\n".join(lines)


def describe_shots(backend: Backend, project: dict, media: dict, shots: list[dict], batch: int = 6) -> dict[int, dict]:
    out: dict[int, dict] = {}
    for i in range(0, len(shots), batch):
        chunk = shots[i:i + batch]
        images: list[Path] = []
        for s in chunk:
            frames = [Path(p) for p in s.get("_frames", []) if Path(p).exists()]
            s["_n_images"] = len(frames)
            images.extend(frames)
        prompt = build_prompt(project, media, chunk)
        data = backend.chat_json(prompt, system=SYSTEM, images=images)
        for item in _shots_from(data):
            try:
                idx = int(item.get("idx"))
            except (TypeError, ValueError):
                continue
            out[idx] = _clean(item)
    return out


def describe_video(backend: Backend, project: dict, media: dict, proxy: Path, shots: list[dict]) -> dict[int, dict]:
    prompt = build_prompt(project, media, shots).replace(
        "每个镜头附 1~2 张关键帧（图片按镜头顺序排列）", "视频已作为附件上传，请按给出的时间段分析")
    data = backend.describe_video(proxy, prompt, system=SYSTEM)
    return {int(it["idx"]): _clean(it) for it in _shots_from(data) if str(it.get("idx", "")).lstrip("-").isdigit()}


def _shots_from(data) -> list[dict]:
    if isinstance(data, dict):
        data = data.get("shots") or data.get("results") or []
    return [d for d in (data or []) if isinstance(d, dict)]


def _clean(item: dict) -> dict:
    cat = str(item.get("category") or "broll").strip()
    if cat not in CATEGORIES:
        cat = "broll"
    try:
        hl = float(item.get("highlight", 0.5))
    except (TypeError, ValueError):
        hl = 0.5
    return {
        "category": cat,
        "description": str(item.get("description") or "")[:200],
        "tags": [str(t) for t in (item.get("tags") or [])][:8],
        "subjects": [str(t) for t in (item.get("subjects") or [])][:6],
        "highlight": max(0.0, min(1.0, hl)),
        "usable": bool(item.get("usable", True)),
        "issues": str(item.get("issues") or ""),
        "text_in_frame": str(item.get("text_in_frame") or ""),
    }
