"""Shared EDL finishing steps: overlays, subtitles, music, voiceover, logo."""
from __future__ import annotations

import re
from pathlib import Path

from .. import config
from ..edl import EDL, AudioItem, Logo, SubtitleCue, TextOverlay
from ..music import pick_track
from ..project import Project
from ..util import read_json, short_hash

_SPLIT_RE = re.compile(r"(?<=[，。！？；,.!?;、])")


class PlanError(RuntimeError):
    pass


def template_vars(pdata: dict) -> dict:
    sp = pdata.get("sponsor") or {}
    ev = pdata.get("event") or {}
    tmpl_cta = (config.get_type(pdata.get("type", "vlog")).get("cta") or "")
    v = {
        "title": pdata.get("title") or pdata.get("name") or "",
        "theme": pdata.get("theme") or "",
        "brand": sp.get("brand") or "",
        "product": sp.get("product") or "",
        "sponsor_cta": sp.get("cta") or "",
        "event_name": ev.get("name") or "",
        "event_location": ev.get("location") or "",
        "event_date": ev.get("date") or "",
    }
    cta = pdata.get("cta") or tmpl_cta
    v["cta"] = fill(cta, v) if cta else ""
    return v


def fill(text: str, vars_: dict) -> str:
    out = re.sub(r"\{(\w+)\}", lambda m: str(vars_.get(m.group(1), "")), text or "")
    out = re.sub(r"\s*·\s*(·\s*)+", " · ", out)
    return out.strip(" ·").strip()


def clean_sub_text(t: str) -> str:
    t = t.strip()
    t = re.sub(r"[。，、；;,.!！?？]+$", "", t)
    t = re.sub(r"[，、；;]", " ", t)
    t = t.replace("。", " ")
    return re.sub(r"\s+", " ", t).strip()


def split_cue(text: str, start: float, end: float, max_chars: int) -> list[SubtitleCue]:
    text = text.strip()
    if not text or end - start < 0.2:
        return []
    pieces: list[str] = []
    for part in _SPLIT_RE.split(text):
        part = part.strip()
        if not part:
            continue
        while len(part) > max_chars:
            cut = part.rfind(" ", 0, max_chars)
            cut = cut if cut > max_chars // 2 else max_chars
            pieces.append(part[:cut])
            part = part[cut:].strip()
        if part:
            if pieces and len(pieces[-1]) + len(part) <= max_chars * 0.6:
                pieces[-1] += part
            else:
                pieces.append(part)
    pieces = [p for p in (clean_sub_text(x) for x in pieces) if p]
    if not pieces:
        return []
    total = sum(len(p) for p in pieces)
    out, t = [], start
    for p in pieces:
        d = (end - start) * len(p) / total
        out.append(SubtitleCue(start=round(t, 3), end=round(t + d, 3), text=p))
        t += d
    return out


def media_transcripts(project: Project) -> dict[str, list[dict]]:
    out = {}
    for m in project.media():
        data = read_json(project.analysis_dir / f"{m['id']}.json")
        if data and data.get("transcript"):
            out[m["id"]] = [s for s in data["transcript"].get("segments", []) if s.get("no_speech_prob", 0) < 0.8]
    return out


def build_subtitles(edl: EDL, project: Project) -> None:
    trans = media_transcripts(project)
    portrait = edl.height > edl.width
    max_chars = 14 if portrait else 20
    cues: list[SubtitleCue] = []
    tl = edl.timeline()
    vo_ranges = [(a.start, a.start + a.duration) for a in edl.audio if a.kind == "voiceover"]
    for c, (cs, ce) in zip(edl.clips, tl):
        if c.volume < 0.5 or c.media_id not in trans:
            continue
        for seg in trans[c.media_id]:
            if seg["end"] <= c.in_ or seg["start"] >= c.out:
                continue
            a = c.src_to_timeline(max(seg["start"], c.in_), cs)
            b = c.src_to_timeline(min(seg["end"], c.out), cs)
            a, b = max(a, cs), min(b, ce)
            if any(a < ve and b > vs for vs, ve in vo_ranges):
                continue
            # only keep a cue if most of the sentence made it into the clip
            frac = (min(seg["end"], c.out) - max(seg["start"], c.in_)) / max(0.01, seg["end"] - seg["start"])
            if b - a >= 0.3 and frac >= 0.6:
                cues += split_cue(seg["text"], a, b, max_chars)
    for a in edl.audio:
        if a.kind != "voiceover":
            continue
        mid = a.src.split("#", 1)[-1] if "#" in a.src else None
        segs = trans.get(mid or "", []) if mid else []
        for seg in segs:
            s0 = a.start + seg["start"] - a.in_
            e0 = a.start + seg["end"] - a.in_
            if e0 > a.start and s0 < a.start + a.duration:
                cues += split_cue(seg["text"], max(s0, a.start), min(e0, a.start + a.duration), max_chars)
    cues.sort(key=lambda q: q.start)
    for i in range(len(cues) - 1):
        if cues[i].end > cues[i + 1].start:
            cues[i].end = round(cues[i + 1].start, 3)
    edl.subtitles = [q for q in cues if q.end - q.start >= 0.2]


def add_music(edl: EDL, project: Project, style: dict, pdata: dict) -> dict | None:
    mcfg = pdata.get("music") or {}
    moods = list(mcfg.get("mood") or []) + list((style.get("music") or {}).get("mood") or [])
    total = edl.total_duration
    track = pick_track(project.root, moods, total, mcfg.get("file") or "")
    if not track:
        edl.notes.append("没有找到配乐：把音乐放进项目 audio/music/，或配置曲库（autocut music scan <目录>）。")
        return None
    vol = mcfg.get("volume")
    if vol is None:
        vol = (style.get("music") or {}).get("volume", (config.settings().get("music") or {}).get("volume", 0.22))
    edl.audio.append(AudioItem(kind="music", src=track["abs_path"], start=0.0, duration=round(total, 3),
                               volume=float(vol), fade_in=1.0, fade_out=min(3.0, total / 4),
                               duck=bool((config.settings().get("music") or {}).get("duck", True)),
                               loop=float(track.get("duration") or 0) < total))
    edl.notes.append(f"配乐：{Path(track['abs_path']).name}（{track.get('source')}，bpm={track.get('bpm', '?')}）"
                     " —— 请确认版权/授权可用于发布平台。")
    return track


def add_voiceover(edl: EDL, project: Project, pdata: dict, start_at: float = 0.0) -> None:
    if not (pdata.get("voiceover") or {}).get("enabled", True):
        return
    vos = [m for m in project.media() if m["kind"] == "audio" and m.get("role") == "voiceover"]
    t = start_at
    total = edl.total_duration
    for m in vos:
        d = float((m.get("probe") or {}).get("duration") or 0)
        if d <= 0 or t >= total:
            continue
        d = min(d, total - t)
        edl.audio.append(AudioItem(kind="voiceover", src=f"{project.media_path(m).resolve()}#{m['id']}", start=round(t, 3),
                                   duration=round(d, 3), volume=1.0, fade_in=0.05, fade_out=0.2))
        t += d + 0.3
    if vos:
        # lower the camera audio under the narration
        tl = edl.timeline()
        for c, (cs, ce) in zip(edl.clips, tl):
            for a in edl.audio:
                if a.kind == "voiceover" and cs < a.start + a.duration and ce > a.start:
                    c.volume = min(c.volume, 0.12)


def add_logo(edl: EDL, project: Project, pdata: dict) -> None:
    sp = pdata.get("sponsor") or {}
    logo = sp.get("logo") or ""
    if not logo:
        if pdata.get("type") == "sponsored":
            edl.notes.append("商单 brief 没有填 logo（project.yaml → sponsor.logo），未加角标。")
        return
    p = Path(logo)
    p = p if p.is_absolute() else project.root / p
    if not p.exists():
        edl.notes.append(f"找不到 logo 文件：{logo}")
        return
    pos = sp.get("logo_position") or "top_right"
    edl.logo = Logo(src=str(p.resolve()), position=pos if pos in ("top_right", "top_left", "bottom_right", "bottom_left") else "top_right")


def section_overlays(edl: EDL, sections: list[dict], marks: list[tuple[str, int, int]], pdata: dict) -> None:
    """marks: (section_id, first_clip_idx, last_clip_idx)."""
    v = template_vars(pdata)
    tl = edl.timeline()
    secmap = {s["id"]: s for s in sections}
    total = edl.total_duration
    for n, (sid, a, b) in enumerate(marks):
        sec = secmap.get(sid, {})
        s0, s1 = tl[a][0], tl[b][1]
        L = s1 - s0
        is_last = n == len(marks) - 1
        if sec.get("text"):
            txt = fill(sec["text"], v)
            if txt:
                if n == 0:
                    edl.overlays.append(TextOverlay(start=round(s0 + 0.2, 3), end=round(s0 + min(3.0, L), 3), text=txt, kind="title"))
                elif is_last and "{cta}" in sec["text"]:
                    edl.overlays.append(TextOverlay(start=round(max(s0, total - 3.5), 3), end=round(total - 0.1, 3), text=txt, kind="cta"))
                else:
                    edl.overlays.append(TextOverlay(start=round(s0 + 0.2, 3), end=round(s0 + min(2.2, L), 3), text=txt, kind="section"))
        if sec.get("lower_third"):
            txt = fill(sec["lower_third"], v)
            if txt:
                edl.overlays.append(TextOverlay(start=round(s0 + 0.4, 3), end=round(s0 + min(3.4, L), 3), text=txt, kind="lower_third"))
        if sec.get("feature_titles"):
            feats = [f for f in ((pdata.get("maker") or {}).get("features") or []) if f]
            for i, f in enumerate(feats):
                fs = s0 + L * i / len(feats)
                edl.overlays.append(TextOverlay(start=round(fs + 0.2, 3), end=round(fs + min(2.5, L / len(feats)), 3),
                                                text=f"功能 {i + 1}：{f}", kind="section"))
        if sec.get("key_messages"):
            msgs = [m for m in ((pdata.get("sponsor") or {}).get("key_messages") or []) if m]
            for i, m in enumerate(msgs):
                ms = s0 + L * i / len(msgs)
                edl.overlays.append(TextOverlay(start=round(ms + 0.2, 3), end=round(ms + max(1.5, L / len(msgs) - 0.3), 3),
                                                text=m, kind="caption"))


def apply_style_meta(edl: EDL, project: Project) -> None:
    pdata = project.load()
    style = project.style()
    W, H = project.resolution()
    edl.project = pdata.get("name", project.root.name)
    edl.title = pdata.get("title", "")
    edl.type = pdata.get("type", "")
    edl.width, edl.height, edl.fps = W, H, int(pdata.get("fps") or 30)
    edl.aspect = str(pdata.get("aspect", "16:9"))
    edl.style = style["id"]
    edl.color_filter = (style.get("color") or {}).get("filter", "")
    lut = (style.get("color") or {}).get("lut") or pdata.get("lut") or ""
    edl.lut = str(lut)
    edl.letterbox = bool(style.get("letterbox")) and W > H
    edl.reframe = (config.settings().get("render") or {}).get("reframe", "auto")
    edl.subtitle_style = dict(style.get("subtitle") or {})
    edl.title_style = dict(style.get("title") or {})


def effect_hash(uid: str) -> float:
    return int(short_hash(uid, n=8), 16) / 0xFFFFFFFF
