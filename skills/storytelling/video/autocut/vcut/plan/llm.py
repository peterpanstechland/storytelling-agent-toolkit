"""LLM planner: model proposes the cut, we validate/clamp it and finish it deterministically."""
from __future__ import annotations

import json

from ..analyze.catalog import build_catalog, transcript_units
from ..backends.base import Backend
from ..config import CATEGORIES
from ..edl import ALL_TRANSITIONS, EDL, Clip, TextOverlay, Transition, EFFECTS
from ..project import Project
from .common import (PlanError, add_logo, add_music, add_voiceover, apply_style_meta, build_subtitles,
                     section_overlays)
from .fxplan import llm_vocab, media_projection, plan_fx, plan_structure, sanitize_llm_clip_fx

SYSTEM = ("你是资深短视频剪辑师，擅长把创作者的原始素材剪成节奏好、信息清楚的成片。"
          "你只能使用给出的素材 ID 和时间范围，不能编造素材。输出严格 JSON。")


def _brief(pdata: dict) -> dict:
    keep = ["name", "type", "type_name", "title", "theme", "target_duration", "aspect", "platforms", "style",
            "voiceover", "cta", "notes", "sponsor", "event", "maker"]
    return {k: pdata[k] for k in keep if k in pdata and pdata[k] not in (None, "", [], {})}


def build_prompt(project: Project, catalog: list[dict], sentences: list[dict], max_units: int = 160) -> str:
    pdata = project.load()
    tmpl = project.type_template()
    style = project.style()
    target = float((pdata.get("sponsor") or {}).get("duration") or pdata.get("target_duration") or 60)
    units = catalog
    if len(units) > max_units:
        keep = sorted(units, key=lambda u: -(u["highlight"] + u["quality"] + (2 if u.get("pinned") else 0)))[:max_units]
        ids = {u["uid"] for u in keep}
        units = [u for u in catalog if u["uid"] in ids]
    lines = []
    for u in units:
        q = f"q={u['quality']:.2f} h={u['highlight']:.2f}"
        issues = ("；问题:" + "/".join(u["quality_notes"])) if u["quality_notes"] else ""
        sp = f"；语音:“{u['speech'][:60]}”" if u["speech"] else ""
        if u.get("projection") == "equirect":
            q += " | 360全景"
        if u.get("activity"):
            q += f" act={u['activity']:.3f}@{u.get('peak_t', 0):.1f}s"
        lines.append(f"{u['uid']} | {u['source_name']} | {u['start']:.1f}-{u['end']:.1f}s | {u['category']} | {q} | "
                     f"{u['description'][:60]}{issues}{sp}")
    sent_lines = [f"{s['uid']} | {s['source_name']} | {s['start']:.1f}-{s['end']:.1f}s | {s['text'][:80]}" for s in sentences[:200]]
    secs = [{"id": s["id"], "name": s.get("name"), "seconds": round(target * float(s.get("ratio", 0.2)), 1),
             "categories": s.get("categories"), "need_voice": bool(s.get("voice"))} for s in tmpl.get("sections", [])]
    return "\n".join([
        f"# 项目 brief\n{json.dumps(_brief(pdata), ensure_ascii=False)}",
        f"\n# 结构模板（{tmpl.get('name')}，目标总时长 {target:.0f} 秒）\n{json.dumps(secs, ensure_ascii=False)}",
        f"\n# 风格（{style.get('name')}）：平均镜头 {style['pacing'].get('avg_shot')}s，最短 {style['pacing'].get('min_shot')}s，"
        f"最长 {style['pacing'].get('max_shot')}s；可用转场 {sorted(ALL_TRANSITIONS)}；风格转场偏好 {style.get('transitions')}",
        f"\n# 运镜/特效词表（可选，不填由程序按风格自动安排；力度 {(style.get('motion') or {}).get('intensity', 0.5)}）\n{llm_vocab()}",
        f"\n# 镜头类别\n{json.dumps(CATEGORIES, ensure_ascii=False)}",
        "\n# 视觉镜头（ref | 文件 | 源时间 | 类别 | 画质q/精彩度h | 描述）\n" + "\n".join(lines),
        "\n# 口播句子（ref | 文件 | 源时间 | 文本）\n" + ("\n".join(sent_lines) or "（无）"),
        "\n# 要求\n"
        "1. 按模板段落顺序排镜头，总时长接近目标；口播段落用口播句子 ref（可把同一文件的连续句子合并成一个片段，in/out 取首句开始和末句结束）。\n"
        "2. 视觉镜头可以只截取其中一部分（in/out 必须落在该镜头的源时间范围内）；同一段素材不要重复使用；优先高画质、高精彩度，避开有问题的镜头。\n"
        "3. 商单必须覆盖 brief 里的 must_show，口播要覆盖 key_messages；不要出现 forbidden 内容。\n"
        "4. 开场 3 秒内要有钩子。\n"
        "5. 运镜/特效要有理由：卡点放大放在节奏强的 B-roll，段落切换用风格的段落转场，动作最激烈处（act@秒）可加 ramp 慢动作或 freeze 定格；"
        "360全景 素材的 move 只能用 360 运镜（开场可 planet_intro）；口播镜头不要加花哨特效。\n"
        "输出 JSON：{\"title\": 片名, \"clips\": [{\"ref\": 镜头或句子ref, \"in\": 源秒, \"out\": 源秒, \"section\": 段落id,"
        " \"role\": 类别, \"transition\": 进入该片段的转场, \"speed\": 1.0, \"move\": 运镜名(可选),"
        " \"fx\": [{\"type\": 特效名, \"start\": 片段内秒, \"dur\": 秒, \"intensity\": 0~1}](可选), \"ramp\": false, \"freeze\": \"定格字(可选)\"}],"
        " \"overlays\": [{\"section\": 段落id, \"text\": 屏幕文字(短), \"kind\": \"caption|section|lower_third\"}],"
        " \"notes\": [给创作者的建议]}",
    ])


def plan_llm(project: Project, backend: Backend) -> EDL:
    pdata = project.load()
    style = project.style()
    tmpl = project.type_template()
    catalog = build_catalog(project)
    if not catalog:
        raise PlanError("没有可用的分析结果：先运行 `autocut analyze`。")
    sentences = transcript_units(project)
    data = backend.chat_json(build_prompt(project, catalog, sentences), system=SYSTEM, temperature=0.4)
    return edl_from_llm(project, data, catalog, sentences, pdata, style, tmpl, planner=f"llm:{backend.name}/{backend.text_model}")


def edl_from_llm(project: Project, data: dict, catalog: list[dict], sentences: list[dict], pdata: dict,
                 style: dict, tmpl: dict, planner: str = "llm") -> EDL:
    if not isinstance(data, dict) or not isinstance(data.get("clips"), list):
        raise PlanError("模型返回的方案缺少 clips 列表")
    units = {u["uid"]: u for u in catalog}
    sents = {s["uid"]: s for s in sentences}
    edl = EDL(planner=planner)
    apply_style_meta(edl, project)
    if data.get("title"):
        edl.notes.append(f"模型建议片名：{data['title']}")
    dur_t = float((style.get("transitions") or {}).get("duration", 0.4))
    dropped = 0
    proj = media_projection(project)
    raw_fx: list[dict] = []
    for i, c in enumerate(data["clips"]):
        if not isinstance(c, dict):
            dropped += 1
            continue
        ref = str(c.get("ref") or c.get("uid") or "")
        u = units.get(ref) or sents.get(ref)
        if not u:
            dropped += 1
            continue
        lo, hi = float(u["start"]), float(u["end"])
        mdur = float(u.get("media_duration") or hi)
        is_sent = ref in sents
        if is_sent:  # allow merging following sentences of the same file
            lo, hi = 0.0, mdur
        try:
            a = float(c.get("in", u["start"]))
            b = float(c.get("out", u["end"]))
        except (TypeError, ValueError):
            a, b = float(u["start"]), float(u["end"])
        a, b = max(lo, min(a, hi)), max(lo, min(b, hi, mdur))
        if b - a < 0.3:
            dropped += 1
            continue
        t = str(c.get("transition") or "cut")
        t = t if t in ALL_TRANSITIONS else "cut"
        effects = [e for e in (c.get("effects") or []) if e in EFFECTS]
        try:
            speed = float(c.get("speed") or 1.0)
        except (TypeError, ValueError):
            speed = 1.0
        role = str(c.get("role") or (u.get("category") if not is_sent else "talking_head"))
        talk = is_sent or role in ("talking_head", "interview")
        edl.clips.append(Clip(
            id=f"c{len(edl.clips) + 1:03d}", media_id=u["media_id"], src=u["path"], **{"in": round(a, 3)}, out=round(b, 3),
            role=role if role in CATEGORIES else "broll", section=str(c.get("section") or ""),
            speed=min(4.0, max(0.25, speed)), effects=effects,
            transition_in=Transition(type=t, duration=0 if t == "cut" else dur_t),
            volume=1.0 if talk else 0.3, note=(u.get("text") or u.get("description") or "")[:60],
            projection="equirect" if proj.get(u["media_id"]) == "equirect" else "flat"))
        raw_fx.append(c)
    if len(edl.clips) < 2:
        raise PlanError(f"模型方案可用片段太少（丢弃 {dropped} 个无效片段）")
    if dropped:
        edl.notes.append(f"模型方案中有 {dropped} 个片段引用无效，已丢弃。")
    for clip, raw in zip(edl.clips, raw_fx):
        sanitize_llm_clip_fx(clip, raw)
    edl.notes += plan_structure(edl, project, style, catalog)
    edl.normalize_transitions()
    # section marks from contiguous section ids
    marks: list[tuple[str, int, int]] = []
    for i, c in enumerate(edl.clips):
        if marks and marks[-1][0] == c.section:
            marks[-1] = (c.section, marks[-1][1], i)
        else:
            marks.append((c.section, i, i))
    track = add_music(edl, project, style, pdata)
    edl.notes += plan_fx(edl, project, style, catalog, marks, tmpl.get("sections", []), track)
    for a in edl.audio:
        if a.kind == "music":
            a.duration = round(edl.total_duration, 3)
    tl = edl.timeline()
    vo_start = next((tl[a][0] for sid, a, _ in marks
                     if next((s for s in tmpl.get("sections", []) if s["id"] == sid), {}).get("voice")), 0.0)
    add_voiceover(edl, project, pdata, vo_start)
    if pdata.get("subtitles", True):
        build_subtitles(edl, project)
    section_overlays(edl, tmpl.get("sections", []), marks, pdata)
    first = {sid: tl[a][0] for sid, a, _ in marks}
    for ov in data.get("overlays") or []:
        if isinstance(ov, dict) and ov.get("text") and ov.get("section") in first:
            s0 = first[ov["section"]] + 0.6
            kind = ov.get("kind") if ov.get("kind") in ("caption", "section", "lower_third") else "caption"
            edl.overlays.append(TextOverlay(start=round(s0, 3), end=round(s0 + 2.5, 3), text=str(ov["text"])[:30], kind=kind))
    for n in data.get("notes") or []:
        edl.notes.append(f"模型建议：{n}")
    add_logo(edl, project, pdata)
    return edl
