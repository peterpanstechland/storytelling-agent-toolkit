"""Planner rules for the ff-tracking-style looks: tracker_hud / lens_look windows and the terminal_hud insert card.

Style palette (config/styles/*.yaml → `hud:`):
  hud:
    tracker: {prob: 0.5, roles: [...], min_dur: 1.8, max_clips: 3, window: 3.0, mode: auto, label: "", collapse: false,
              lens: {palette: thermal, palette_mix: 0.7, dof: 0.8}, lock: peak|beat}
    terminal: {enabled: true, position: after_hook|before_cta|start, lines: [], title: agent, done: Done,
               palettes: [...], lens: {...}, only_types: [maker]}
    sfx: true
Where things go:
  * tracker_hud: product / detail / screen / build / demo shots (never talking heads); the lock lands on the beat
    nearest the action peak (or 55 % of the shot); the last one can collapse into a label pill.
  * terminal_hud card: maker / tech projects (or when project.yaml has `terminal:`), after the hook section, text from
    the brief (project title, maker.features) unless `terminal.lines` is given.
"""
from __future__ import annotations

from pathlib import Path

from ..edl import EDL, FX, Clip, Transition
from ..project import Project
from ..util import short_hash

NO_HUD_ROLES = {"talking_head", "interview", "selfie", "card"}


def _h(*parts) -> float:
    return int(short_hash(*parts, n=8), 16) / 0xFFFFFFFF


def terminal_lines(pdata: dict, tcfg: dict) -> list[str]:
    """Card text: project.yaml `terminal.lines` → style `hud.terminal.lines` → brief (title, maker.features)."""
    own = (pdata.get("terminal") or {}) if isinstance(pdata.get("terminal"), dict) else {}
    lines = [str(x) for x in (own.get("lines") or tcfg.get("lines") or []) if str(x).strip()]
    if lines:
        return lines[:6]
    title = str(pdata.get("title") or pdata.get("name") or "").strip()
    feats = [str(f).strip() for f in ((pdata.get("maker") or {}).get("features") or []) if str(f).strip()]
    out = []
    if title:
        out.append(title[:28])
    out += [f[:28] for f in feats[:3]]
    return out[:5] if len(out) >= 2 else []


def insert_terminal_card(edl: EDL, project: Project, style: dict, marks: list[tuple[str, int, int]]):
    """Insert the generated terminal card clip. Returns (marks, note|None). Must run before the timeline is computed."""
    from ..fx.terminal import card_duration

    hcfg = style.get("hud") or {}
    tcfg = hcfg.get("terminal") or {}
    pdata = project.load()
    if not tcfg.get("enabled") or not edl.clips or any(c.generated for c in edl.clips):
        return marks, None
    only = tcfg.get("only_types")
    own = pdata.get("terminal") if isinstance(pdata.get("terminal"), dict) else None
    if own is None and only and pdata.get("type") not in only:
        return marks, None
    if own is not None and own.get("enabled") is False:
        return marks, None
    lines = terminal_lines(pdata, tcfg)
    if not lines:
        return marks, None
    spec = {"type": "terminal_hud", "lines": lines, "title": str((own or {}).get("title") or tcfg.get("title") or "agent"),
            "status": str((own or {}).get("status") or tcfg.get("status") or "ready"), "done": (own or {}).get("done", tcfg.get("done", "Done")),
            "palettes": tcfg.get("palettes") or None, "lens": tcfg.get("lens") or {}, "sfx": bool(hcfg.get("sfx", True))}
    spec = {k: v for k, v in spec.items() if v not in (None, {})}
    dur = card_duration(spec)
    pos = str(tcfg.get("position", "after_hook"))
    n = len(edl.clips)
    if pos == "start":
        idx = 0
    elif pos == "before_cta":
        idx = marks[-1][1] if marks else max(0, n - 1)
    else:
        idx = marks[1][1] if len(marks) > 1 else min(1, n)
    idx = max(0, min(idx, n))
    prev_sec = edl.clips[idx - 1].section if idx > 0 else edl.clips[0].section
    c = Clip(id="terminal1", media_id="", src="", role="card", section=prev_sec, **{"in": 0.0}, out=round(dur, 3),
             note="终端 HUD 插卡（程序生成）", generated=spec)
    c.transition_in = Transition(type="glitch", duration=0.25) if idx > 0 else Transition(type="cut", duration=0.0)
    edl.clips.insert(idx, c)
    new_marks = []
    for sid, a, b in marks:   # the card joins the section before it
        if a >= idx:
            a, b = a + 1, b + 1
        elif b >= idx - 1:
            b += 1
        new_marks.append((sid, a, b))
    return new_marks, f"终端 HUD 插卡 {dur:.1f}s（{len(lines)} 行，位置 {pos}）。"


def plan_tracker_hud(edl: EDL, project: Project, style: dict, catalog: list[dict], tl: list[tuple[float, float]]) -> list[str]:
    from ..fx.lens import PALETTES
    from .fxplan import unit_for

    hcfg = style.get("hud") or {}
    tcfg = hcfg.get("tracker") or {}
    if not tcfg or float(tcfg.get("prob", 0)) <= 0:
        return []
    pdata = project.load()
    roles = set(tcfg.get("roles") or ["product", "detail", "screen", "build", "demo", "broll", "action"])
    min_dur = float(tcfg.get("min_dur", 1.8))
    max_clips = int(tcfg.get("max_clips", 3))
    win = float(tcfg.get("window", 3.0))
    lens = dict(tcfg.get("lens") or {})
    if lens.get("palette") and lens["palette"] not in PALETTES:
        lens.pop("palette")
    label = str(tcfg.get("label") or pdata.get("title") or "Done")[:16]
    done: list[tuple[int, FX]] = []
    last_i = -9
    for i, c in enumerate(edl.clips):
        if len(done) >= max_clips:
            break
        if c.generated or c.role in NO_HUD_ROLES or c.role not in roles or c.duration < min_dur or i - last_i < 2:
            continue
        if any(f.type in ("tracker_hud",) for f in c.fx):
            continue
        if _h(c.id, c.media_id, c.in_, "hud") >= float(tcfg.get("prob", 0)):
            continue
        u = unit_for(c, catalog) or {}
        dur = c.duration
        want = dur * 0.55
        if str(tcfg.get("lock", "peak")) == "peak" and u.get("peak_t") is not None:
            want = c.src_to_timeline(min(max(float(u["peak_t"]), c.in_), c.out), 0.0)
        start = max(0.0, min(want - win * 0.55, dur - min(win, dur)))
        wdur = min(win, dur - start)
        cand = [b - tl[i][0] for b in edl.beats if tl[i][0] + start + 0.5 <= b <= tl[i][0] + start + wdur - 0.45]
        lock = min(cand, key=lambda b: abs(b - want)) if cand else min(max(want, start + 0.5), start + wdur - 0.45)
        params: dict = {"locks": [round(lock, 3)], "mode": tcfg.get("mode", "auto")}
        if tcfg.get("hatch"):
            params["hatch"] = tcfg["hatch"]
        if tcfg.get("color"):
            params["color"] = tcfg["color"]
        done.append((i, FX(type="tracker_hud", start=round(start, 3), dur=round(wdur, 3),
                           intensity=float(tcfg.get("intensity", 0.9)), params=params)))
        last_i = i
    if not done:
        return []
    if tcfg.get("collapse") and done:
        i, f = done[-1]
        end = (f.start or 0) + (f.dur or 0)
        if (f.dur or 0) >= 2.0:
            f.params["collapse_at"] = round(max(f.params["locks"][0] + 0.35, end - 1.2), 3)
            f.params["label"] = label
    for i, f in done:
        c = edl.clips[i]
        if lens:
            c.fx.append(FX(type="lens_look", start=f.start, dur=f.dur, intensity=float(tcfg.get("lens_intensity", 0.85)),
                           params={k: v for k, v in lens.items()}))
        c.fx.append(f)
    return [f"追踪框 HUD {len(done)} 段（锁定点落在动作峰值/节拍上" + ("，附 lens_look 镜头质感" if lens else "") + "）。"]


def plan_hud_sfx(edl: EDL, project: Project, style: dict, tl: list[tuple[float, float]], vol: float) -> int:
    """Lock beeps for tracker_hud windows (panned by the subject position when known) + the terminal card bed."""
    from ..edl import AudioItem
    from ..fx.sfx import get_hud_track, get_lock_beep
    from ..fx.terminal import schedule

    if not (style.get("hud") or {}).get("sfx", True):
        return 0
    cache = project.root / "cache" / "sfx"
    n = 0
    for i, c in enumerate(edl.clips):
        s = tl[i][0]
        if c.generated and c.generated.get("sfx", True):
            sched = schedule(c.generated)
            p = get_hud_track(sched, cache, seed=int(short_hash(c.id, n=6), 16) % 9973)
            edl.audio.append(AudioItem(kind="sfx", tag="terminal", src=str(p), start=round(s, 3), duration=round(c.duration, 3),
                                       volume=round(vol, 3)))
            n += 1
            continue
        for f in c.fx:
            if f.type != "tracker_hud":
                continue
            for k, lt in enumerate(f.params.get("locks") or []):
                t = s + float(lt)
                pan = 0.0
                if c.focus_track:
                    near = min(c.focus_track, key=lambda q: abs(q[0] - lt))
                    pan = max(-0.8, min(0.8, (float(near[1]) - 0.5) * 1.6))
                p = get_lock_beep(cache, pitch=n)
                edl.audio.append(AudioItem(kind="sfx", tag="lock_beep", src=str(p), start=round(t, 3), duration=0.3,
                                           volume=round(vol * 0.9, 3), pan=round(pan, 2)))
                n += 1
    return n
