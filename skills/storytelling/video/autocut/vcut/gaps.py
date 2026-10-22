"""vcut gaps: compare analyzed footage vs shot list → 补拍提醒."""
from __future__ import annotations

from . import config
from .analyze.catalog import build_catalog, transcript_units
from .devices import device_labels_for
from .project import Project
from .shotlist import generate_shotlist
from .util import ok


def _blob(u: dict) -> str:
    return " ".join([u.get("description", ""), " ".join(u.get("tags", [])), u.get("text_in_frame", ""),
                     u.get("speech", ""), u.get("source_name", "")]).lower()


def find_gaps(project: Project) -> dict:
    pdata = project.load()
    sl = project.root / "shotlist.yaml"
    if not sl.exists():
        generate_shotlist(project, backend_name="none")
    items = (config.load_yaml(sl) or {}).get("items", [])
    catalog = build_catalog(project, include_unusable=True)
    usable = [u for u in catalog if u["quality"] >= 0.35]
    has_vision = any(u["category_source"] in ("vision", "label") for u in catalog)
    results = []
    for it in items:
        kws = [k.lower() for k in it.get("keywords") or [] if k]
        cat = it.get("category")
        by_cat = [u for u in usable if u["category"] == cat]
        by_kw = [u for u in usable if kws and any(k in _blob(u) for k in kws)]
        if it.get("source") == "brief":   # brief items need content evidence, not just a category
            matched = by_kw
        else:
            matched = {u["uid"]: u for u in by_cat + by_kw}.values()
        matched = list(matched)
        secs = sum(u["duration"] for u in matched)
        need = float(it.get("min_seconds") or 5)
        status = "ok" if secs >= need else ("low" if secs > 0 else "missing")
        results.append({"id": it.get("id"), "name": it.get("name"), "required": bool(it.get("required")),
                        "category": cat, "seconds": round(secs, 1), "need": need, "status": status,
                        "examples": [u["uid"] for u in matched[:3]], "devices": device_labels_for(it.get("devices") or []),
                        "desc": it.get("desc", ""), "source": it.get("source", "template")})
    media = project.media()
    raw360 = [m for m in media if m.get("needs_export")]
    poor = [u for u in catalog if u["quality_notes"]]
    speech_secs = sum(s["end"] - s["start"] for s in transcript_units(project))
    total_usable = sum(u["duration"] for u in usable)
    target = float((pdata.get("sponsor") or {}).get("duration") or pdata.get("target_duration") or 60)
    report = {"items": results, "has_vision": has_vision, "raw360": [m["source_name"] for m in raw360],
              "poor_quality": [{"uid": u["uid"], "file": u["source_name"], "time": f"{u['start']:.1f}-{u['end']:.1f}s",
                                "notes": u["quality_notes"]} for u in poor[:15]],
              "speech_seconds": round(speech_secs, 1), "usable_seconds": round(total_usable, 1), "target": target,
              "voiceover_needed": bool((pdata.get("voiceover") or {}).get("enabled"))}
    md = render_markdown(project, report)
    (project.analysis_dir / "gaps.md").write_text(md, encoding="utf-8")
    report["markdown"] = md
    return report


def render_markdown(project: Project, r: dict) -> str:
    icon = {"ok": "✅", "low": "⚠️", "missing": "❌"}
    pdata = project.load()
    lines = [f"# 素材检查 / 补拍提醒：{pdata.get('title')}", ""]
    lines.append(f"- 可用素材 {r['usable_seconds']:.0f}s，目标成片 {r['target']:.0f}s"
                 + ("（素材偏少，建议至少是成片的 3 倍）" if r["usable_seconds"] < r["target"] * 3 else ""))
    if r["voiceover_needed"]:
        lines.append(f"- 识别到说话 {r['speech_seconds']:.0f}s" + ("（口播偏少，需要补录口播）" if r["speech_seconds"] < r["target"] * 0.25 else ""))
    if not r["has_vision"]:
        lines.append("- ℹ️ 当前没有画面理解（离线模式），镜头类别是按设备/说话/文件名推断的，下面结果仅供参考。"
                     "配置 AI 后端后重新 `autocut analyze`，或在 analysis/labels.yaml 里手动标注。")
    lines.append("")
    missing = [i for i in r["items"] if i["status"] != "ok" and i["required"]]
    if missing:
        lines += ["## 🎬 需要补拍（必拍项）"]
        for i in missing:
            lines.append(f"- {icon[i['status']]} **{i['name']}**：已有 {i['seconds']:.0f}s / 需要 {i['need']:.0f}s｜📷 "
                         f"{' / '.join(i['devices']) or '任意设备'}｜{i['desc']}")
        lines.append("")
    lines += ["## 全部镜头覆盖情况", "| 状态 | 镜头 | 必拍 | 已有/需要 | 示例 |", "|---|---|---|---|---|"]
    for i in r["items"]:
        lines.append(f"| {icon[i['status']]} | {i['name']} | {'是' if i['required'] else '否'} | {i['seconds']:.0f}s/{i['need']:.0f}s | "
                     f"{', '.join(i['examples'])} |")
    if r["raw360"]:
        lines += ["", "## 360° 原始文件还没导出", *[f"- {n}" for n in r["raw360"]],
                  "在 Insta360 Studio 导出 2:1 全景 MP4（或重构图后的平面 MP4）再 `autocut ingest`。"]
    if r["poor_quality"]:
        lines += ["", "## 画质问题镜头（规划时会尽量避开）"]
        lines += [f"- {p['file']} {p['time']}：{'、'.join(p['notes'])}" for p in r["poor_quality"]]
    return "\n".join(lines)


def print_gaps(project: Project) -> dict:
    r = find_gaps(project)
    from .util import console
    from rich.markdown import Markdown

    console.print(Markdown(r["markdown"]))
    ok(f"报告：{project.analysis_dir / 'gaps.md'}")
    return r
