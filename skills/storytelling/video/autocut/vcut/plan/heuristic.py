"""Deterministic rule-based planner (works fully offline, no model needed)."""
from __future__ import annotations

import math
from collections import defaultdict

from ..analyze.catalog import build_catalog, transcript_units
from ..edl import EDL, Clip, Transition
from ..project import Project
from .common import (PlanError, add_logo, add_music, add_voiceover, apply_style_meta, build_subtitles,
                     effect_hash, section_overlays)
from .fxplan import plan_fx, plan_structure

TALK_CATS = {"talking_head", "interview", "selfie"}


def _overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


class _Picker:
    def __init__(self, catalog: list[dict], sentences: list[dict], style: dict, pdata: dict):
        self.catalog = catalog
        self.style = style
        self.pdata = pdata
        self.pacing = style.get("pacing") or {}
        self.used: dict[str, list[tuple[float, float]]] = defaultdict(list)
        self.media_uses: dict[str, int] = defaultdict(int)
        self.unit_bounds: dict[str, tuple[float, float]] = {}
        talk_units = [u for u in catalog if u["category"] in TALK_CATS]
        self.sentences = [s for s in sentences
                          if any(u["media_id"] == s["media_id"] and _overlap(u["start"], u["end"], s["start"], s["end"]) > 0
                                 for u in talk_units)]
        self.n_clip = 0

    def is_free(self, mid: str, s: float, e: float, tol: float = 0.25) -> bool:
        return all(_overlap(s, e, a, b) <= tol * (e - s) for a, b in self.used[mid])

    def find_window(self, mid: str, lo: float, hi: float, L: float) -> float | None:
        """Free [s, s+L] inside [lo, hi], as close to the centre as possible (no reuse of footage)."""
        if hi - lo < L - 1e-6:
            return None
        centre = lo + (hi - lo - L) / 2
        steps = 24
        cands = sorted({round(lo + (hi - lo - L) * k / steps, 3) for k in range(steps + 1)}, key=lambda x: abs(x - centre))
        for s in cands:
            if all(_overlap(s, s + L, a, b) <= 0.05 for a, b in self.used[mid]):
                return s
        return None

    def take(self, mid: str, s: float, e: float) -> None:
        self.used[mid].append((s, e))
        self.media_uses[mid] += 1

    # ---------- speech ----------
    def speech(self, budget: float, sec: dict, from_end: bool = False) -> list[Clip]:
        cands = [s for s in self.sentences if self.is_free(s["media_id"], s["start"], s["end"], 0.1)]
        if from_end:
            cands = list(reversed(cands))
        chosen, total = [], 0.0
        for s in cands:
            d = s["end"] - s["start"]
            if total + d > budget * 1.35 and chosen:
                break
            chosen.append(s)
            total += d
            if total >= budget:
                break
        chosen.sort(key=lambda s: (s["creation_time"] or "", s["source_name"] or "", s["start"]))
        groups: list[list[dict]] = []
        for s in chosen:
            if groups and groups[-1][-1]["media_id"] == s["media_id"] and s["start"] - groups[-1][-1]["end"] < 0.8:
                groups[-1].append(s)
            else:
                groups.append([s])
        clips = []
        for g in groups:
            mid = g[0]["media_id"]
            a = max(0.0, g[0]["start"] - 0.12)
            b = min(g[-1]["media_duration"] or g[-1]["end"] + 0.25, g[-1]["end"] + 0.25)
            self.take(mid, a, b)
            clips.append(self._clip(mid, g[0]["path"], a, b, role="talking_head", section=sec["id"], volume=1.0,
                                    note=" ".join(x["text"] for x in g)[:80]))
        return clips

    # ---------- visuals ----------
    def visual(self, budget: float, sec: dict, mode: str, keywords: list[str] | None = None) -> list[Clip]:
        if budget <= 0.3:
            return []
        cats = list(sec.get("categories") or [])
        is_hook = sec["id"] == "hook"
        avg = float(self.pacing.get("hook_shot" if is_hook else "avg_shot", 2.5))
        min_shot = float(self.pacing.get("min_shot", 1.0))
        max_shot = float(self.pacing.get("max_shot", 5.0))
        if is_hook:
            min_shot = min(min_shot, avg)

        def free(u):
            return self.is_free(u["media_id"], u["start"], u["end"], 0.5) and u["duration"] >= min_shot * 0.8

        cands = [u for u in self.catalog if u["category"] in cats and free(u)]
        if self.sentences:
            # spoken material is reserved for the speech picker (never chop sentences as B-roll)
            cands = [u for u in cands if u["speech_ratio"] < 0.3]
        elif sec.get("voice") is False:
            cands = [u for u in cands if u["category"] not in TALK_CATS or u["speech_ratio"] < 0.3] or cands
        fallback = False
        if not cands:
            cands = [u for u in self.catalog if free(u) and u["category"] not in TALK_CATS and u["speech_ratio"] < 0.3]
            fallback = bool(cands)
        if not cands:
            return []

        kw = [k.lower() for k in (keywords or []) if k]

        def score(u):
            s = 0.55 * u["highlight"] + 0.45 * u["quality"]
            if u["category"] in cats:
                s += 0.15 * (1 - cats.index(u["category"]) / max(1, len(cats)))
            s -= 0.08 * self.media_uses[u["media_id"]]
            if u.get("pinned"):
                s += 1.0
            if kw:
                blob = " ".join([u["description"], " ".join(u["tags"]), u["text_in_frame"], u["speech"]]).lower()
                if any(k in blob for k in kw):
                    s += 1.0
            return s

        ranked = sorted(cands, key=lambda u: (-score(u), u["order"]))
        chosen, total = [], 0.0
        for u in ranked:
            if total >= budget:
                break
            if not self.is_free(u["media_id"], u["start"], u["end"], 0.5):
                continue
            jitter = 0.75 + 0.5 * effect_hash(u["uid"])
            L = max(min_shot, min(max_shot, avg * jitter))
            L = min(L, u["duration"], max(min_shot, budget - total + 0.3))
            s0 = self.find_window(u["media_id"], u["start"], u["end"], L)
            if s0 is None:
                continue
            self.take(u["media_id"], s0, s0 + L)
            chosen.append((u, s0, s0 + L))
            total += L
        if not is_hook:
            chosen.sort(key=lambda x: x[0]["order"])
        clips = []
        for u, a, b in chosen:
            c = self._clip(u["media_id"], u["path"], a, b, role=u["category"], section=sec["id"],
                           volume=0.6 if self.pdata.get("type") == "vlog" and sec.get("voice") else 0.3,
                           note=(u["description"] or "")[:60] + (" [备选素材]" if fallback else ""))
            self.unit_bounds[c.id] = (u["start"], u["end"])
            self._effects(c, u)
            clips.append(c)
        return clips

    def _effects(self, c: Clip, u: dict) -> None:
        eff = self.style.get("effects") or {}
        h = effect_hash(u["uid"])
        if eff.get("speed_ramp") and u["category"] in ("action", "pov", "build", "crowd") and c.src_duration >= 2.2 and h > 0.5:
            c.effects.append("speed_ramp")
        elif h < float(eff.get("zoom_prob", 0.3)):
            c.effects.append("zoom_in" if int(h * 1000) % 2 == 0 else "zoom_out")

    def _clip(self, mid, path, a, b, *, role, section, volume, note="") -> Clip:
        self.n_clip += 1
        return Clip(id=f"c{self.n_clip:03d}", media_id=mid, src=path, **{"in": round(a, 3)}, out=round(b, 3),
                    role=role, section=section, volume=volume, note=note)


def _interleave(a: list[Clip], b: list[Clip]) -> list[Clip]:
    if not a or not b:
        return a + b
    out = []
    ratio = len(b) / len(a)
    j = 0.0
    bi = 0
    for c in a:
        out.append(c)
        j += ratio
        while bi < len(b) and bi < math.floor(j + 1e-9):
            out.append(b[bi])
            bi += 1
    out += b[bi:]
    return out


def assign_transitions(edl: EDL, style: dict, marks: list[tuple[str, int, int]]) -> None:
    tcfg = style.get("transitions") or {}
    within = tcfg.get("within") or ["cut"]
    section = tcfg.get("section") or ["fade"]
    dur = float(tcfg.get("duration", 0.4))
    starts = {a for _, a, _ in marks}
    k_sec = k_in = 0
    for i, c in enumerate(edl.clips):
        if i == 0:
            continue
        prev = edl.clips[i - 1]
        if i in starts:
            t = section[k_sec % len(section)]
            k_sec += 1
        elif c.role == "talking_head" and prev.role == "talking_head":
            t = "cut"
        else:
            t = within[k_in % len(within)]
            k_in += 1
        c.transition_in = Transition(type=t, duration=0.0 if t == "cut" else dur)


def beat_snap(edl: EDL, beats: list[float], bounds: dict[str, tuple[float, float]], min_shot: float) -> int:
    """Nudge B-roll cut points onto music beats. Returns number of snapped cuts."""
    if not beats:
        return 0
    snapped = 0
    t = 0.0
    for i, c in enumerate(edl.clips):
        if i > 0:
            t -= c.transition_in.duration
        if c.id in bounds and c.role != "talking_head" and "speed_ramp" not in c.effects and not c.ramp and not c.freeze:
            lo, hi = bounds[c.id]
            end = t + c.duration
            cands = [b for b in beats if abs(b - end) <= 0.45 and b - t >= min_shot * 0.8]
            if cands:
                b = min(cands, key=lambda x: abs(x - end))
                new_out = c.in_ + (b - t) * c.speed
                if new_out <= hi and new_out > c.in_ + 0.3:
                    c.out = round(new_out, 3)
                    snapped += 1
                elif lo <= c.in_ - (new_out - hi) and new_out > hi:
                    shift = new_out - hi
                    c.in_, c.out = round(c.in_ - shift, 3), round(hi, 3)
                    snapped += 1
        t += c.duration
    return snapped


def plan_heuristic(project: Project) -> EDL:
    pdata = project.load()
    tmpl = project.type_template()
    style = project.style()
    catalog = build_catalog(project)
    if not catalog:
        raise PlanError("没有可用的分析结果：先运行 `autocut analyze`。")
    sentences = transcript_units(project)
    target = float((pdata.get("sponsor") or {}).get("duration") or pdata.get("target_duration") or 60)
    picker = _Picker(catalog, sentences, style, pdata)
    must_show = list((pdata.get("sponsor") or {}).get("must_show") or [])
    sections = list(tmpl.get("sections") or [])

    edl = EDL(planner="heuristic")
    apply_style_meta(edl, project)
    marks: list[tuple[str, int, int]] = []
    for sec in sections:
        budget = target * float(sec.get("ratio", 0.2))
        mode = sec.get("pick", "best")
        speech_clips: list[Clip] = []
        if mode in ("speech", "speech_or_best"):
            share = 1.0 if mode == "speech" else 0.6
            speech_clips = picker.speech(budget * share, sec, from_end=sec["id"] == "outro")
        used = sum(c.duration for c in speech_clips)
        visual_clips: list[Clip] = []
        remaining = budget - used
        if mode in ("best", "chronological", "must_show") or (mode == "speech_or_best" and remaining > 0.2 * budget) \
                or (mode == "speech" and not speech_clips):
            kws = must_show if mode == "must_show" else None
            visual_clips = picker.visual(remaining, sec, mode, kws)
        if mode == "speech" and not speech_clips:
            edl.notes.append(f"段落「{sec.get('name')}」需要口播，但没有识别到说话的素材（检查是否安装 ASR 或补拍口播）。")
        clips = _interleave(speech_clips, visual_clips)
        if not clips:
            edl.notes.append(f"段落「{sec.get('name')}」没有合适素材，已跳过。")
            continue
        a = len(edl.clips)
        edl.clips.extend(clips)
        marks.append((sec["id"], a, len(edl.clips) - 1))
        if any("[备选素材]" in c.note for c in visual_clips):
            edl.notes.append(f"段落「{sec.get('name')}」缺少理想镜头类型 {sec.get('categories')}，用其它素材顶替。")

    if not edl.clips:
        raise PlanError("素材不足，无法生成剪辑方案。")
    assign_transitions(edl, style, marks)
    edl.notes += plan_structure(edl, project, style, catalog)
    edl.normalize_transitions()

    track = add_music(edl, project, style, pdata)
    beat_sync = (pdata.get("music") or {}).get("beat_sync")
    if beat_sync is None:
        beat_sync = bool(style.get("beat_sync"))
    if track and beat_sync and track.get("beats"):
        n = beat_snap(edl, track["beats"], picker.unit_bounds, float((style.get("pacing") or {}).get("min_shot", 1.0)))
        edl.normalize_transitions()
        edl.audio[-1].duration = round(edl.total_duration, 3)
        edl.notes.append(f"卡点：{n} 个剪辑点对齐到音乐节拍。")

    edl.notes += plan_fx(edl, project, style, catalog, marks, sections, track)
    for a in edl.audio:
        if a.kind == "music":
            a.duration = round(edl.total_duration, 3)
    start_vo = 0.0
    tl = edl.timeline()
    for sid, a, _ in marks:
        if next((s for s in sections if s["id"] == sid), {}).get("voice"):
            start_vo = tl[a][0]
            break
    add_voiceover(edl, project, pdata, start_vo)
    if pdata.get("subtitles", True):
        build_subtitles(edl, project)
    section_overlays(edl, sections, marks, pdata)
    add_logo(edl, project, pdata)
    total = edl.total_duration
    if total < target * 0.7:
        edl.notes.append(f"成片 {total:.0f}s，比目标 {target:.0f}s 短很多：素材不够，看 `autocut gaps` 补拍。")
    return edl
