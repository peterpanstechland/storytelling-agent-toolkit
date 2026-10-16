"""v2 motion/effects planner — applies the style palette (motion / fx / sfx / text_anims / progress / jianying)
to an EDL. Shared by the heuristic and the LLM planner (the LLM's own choices are validated and kept).

Two phases:
  plan_structure()  — things that change clip durations (360 projection, speed ramps, freeze frames).
                      Run BEFORE transitions are normalized / cuts are beat-snapped.
  plan_fx()         — everything that sits on the final timeline: camera moves, beat punch-ins, effect
                      windows, white flashes on downbeats, whip-pans between 360 headings, SFX, text animation
                      presets, progress bar, 剪映 hints.
Where to put effects (the "sensible" part):
  * beats / downbeats of the chosen music → punch-ins, beat flashes (never inside talking-head clips)
  * section changes → the style's section transition + accent effect + riser→hit SFX
  * action peaks (frame-difference maximum per shot, from analysis) → speed ramp slowing at the peak,
    freeze frame + callout, speed lines
"""
from __future__ import annotations

import math
from pathlib import Path

from .. import config
from ..edl import (CUSTOM_TRANSITIONS, EDL, FX, FX_TYPES, MOVES_2D, MOVES_360, Clip, Freeze, Move, PIP, Ramp,
                   TextOverlay, Transition)
from ..project import Project
from ..util import short_hash

PEOPLE = {"talking_head", "interview", "selfie"}
ACTIONY = {"action", "pov", "crowd", "build"}


def _h(*parts) -> float:
    return int(short_hash(*parts, n=8), 16) / 0xFFFFFFFF


def _pick(seq, key: float):
    seq = [s for s in (seq if isinstance(seq, list) else [seq]) if s]
    return seq[int(key * len(seq)) % len(seq)] if seq else None


def unit_for(clip: Clip, catalog: list[dict]) -> dict | None:
    best, ov = None, 0.0
    for u in catalog:
        if u["media_id"] != clip.media_id:
            continue
        o = min(u["end"], clip.out) - max(u["start"], clip.in_)
        if o > ov:
            best, ov = u, o
    return best


def media_projection(project: Project) -> dict[str, str]:
    return {m["id"]: m.get("projection", "flat") for m in project.media()}


# ------------------------------------------------------------------ phase A
def plan_structure(edl: EDL, project: Project, style: dict, catalog: list[dict], *, keep_existing: bool = True) -> list[str]:
    """Projection, speed ramps at action peaks, freeze frames. Returns notes."""
    motion = style.get("motion") or {}
    proj = media_projection(project)
    notes: list[str] = []
    rcfg = motion.get("ramp") or {}
    fcfg = motion.get("freeze") or {}
    n_freeze = sum(1 for c in edl.clips if c.freeze)
    acts = sorted([u.get("activity", 0.0) for u in catalog]) or [0.0]
    hi_act = acts[int(0.6 * (len(acts) - 1))]
    for c in edl.clips:
        u = unit_for(c, catalog) or {}
        if proj.get(c.media_id) == "equirect" or u.get("projection") == "equirect":
            c.projection = "equirect"
        if not motion:
            continue
        # legacy v1 flags → v2 (better looking) equivalents
        if "speed_ramp" in c.effects:
            c.effects.remove("speed_ramp")
            if c.ramp is None:
                c.ramp = Ramp()
        for old, new in (("zoom_in", "push_in"), ("zoom_out", "pull_out")):
            if old in c.effects:
                c.effects.remove(old)
                if c.move is None:
                    c.move = Move(type=new)
        if c.role in PEOPLE:
            continue
        peak = float(u.get("peak_t", (c.in_ + c.out) / 2))
        rel = (peak - c.in_) / max(0.01, c.src_duration)
        k = _h(c.id, c.media_id, c.in_, "struct")
        if (c.ramp is None and c.role in set(rcfg.get("roles") or []) and c.src_duration >= 2.0
                and k < float(rcfg.get("prob", 0)) * (1.4 if u.get("activity", 0) >= hi_act else 0.8)):
            x = min(0.75, max(0.3, rel))
            c.ramp = Ramp(profile=[[0, 1.0], [max(0.05, x - 0.18), 1.0], [x - 0.04, 0.3], [x + 0.14, 0.3],
                                   [min(0.97, x + 0.28), 1.6], [1, 1.9]], interp=rcfg.get("interp", "blend"))
        elif (c.freeze is None and c.ramp is None and n_freeze < int(fcfg.get("max", 0)) and c.src_duration >= 1.6
              and c.role in (ACTIONY | {"product", "detail", "screen"}) and (1 - k) < float(fcfg.get("prob", 0))):
            at = min(c.src_duration - 0.4, max(0.4, peak - c.in_)) / c.speed
            txt = ""
            feats = [f for f in ((project.load().get("maker") or {}).get("features") or []) if f]
            if feats:
                txt = str(feats[n_freeze % len(feats)])[:12]
            c.freeze = Freeze(at=round(at, 3), hold=1.0, text=txt, style="pop")
            n_freeze += 1
    if motion.get("whip360"):  # whip-pan between consecutive 360 shots (heading change)
        for i in range(1, len(edl.clips)):
            a, b = edl.clips[i - 1], edl.clips[i]
            if a.projection == b.projection == "equirect" and b.transition_in.type in ("cut", "fade", "dissolve"):
                b.transition_in = Transition(type="whip_left" if _h(b.id, "w") < 0.5 else "whip_right", duration=0.35)
    if any(c.projection == "equirect" for c in edl.clips):
        notes.append(f"360° 素材 {sum(c.projection == 'equirect' for c in edl.clips)} 段：自动运镜（重构图到 {edl.width}x{edl.height}）。")
    return notes


# ------------------------------------------------------------------ phase B helpers
def timeline_beats(track: dict | None, total: float) -> tuple[list[float], list[float]]:
    if not track or not track.get("beats"):
        return [], []
    beats = [float(b) for b in track["beats"]]
    downs = [float(b) for b in (track.get("downbeats") or [])] or beats[::4]
    mdur = float(track.get("duration") or 0)
    if mdur > 0 and mdur < total:  # music loops
        out_b, out_d, off = [], [], 0.0
        while off < total:
            out_b += [b + off for b in beats]
            out_d += [b + off for b in downs]
            off += mdur
        beats, downs = out_b, out_d
    return ([round(b, 3) for b in beats if 0 < b < total - 0.05], [round(b, 3) for b in downs if 0 < b < total - 0.05])


def _at(cfg: dict, default: str = "none") -> str:
    """YAML 1.1 parses a bare `on:` key as boolean True — accept `at`, `on` and True."""
    return str(cfg.get("at", cfg.get("on", cfg.get(True, default))))


def _clip_at(tl, t):
    for i, (s, e) in enumerate(tl):
        if s <= t < e:
            return i
    return None


def _yaw_track(edl: EDL, project: Project, c: Clip) -> None:
    from ..fx.track import track_360

    src = Path(c.src) if Path(c.src).is_absolute() else project.root / c.src
    try:
        res = track_360(src, c.in_, c.src_duration)
    except Exception:  # noqa: BLE001 — tracking is best-effort, fixed heading otherwise
        return
    tr = res.get("track") or []
    if tr and c.speed != 1.0:
        tr = [[round(t / c.speed, 3), y, p] for t, y, p in tr]
    if tr and (c.ramp or c.freeze):  # source-relative → clip-local output time
        tr = [[round(c.src_to_timeline(c.in_ + t, 0.0), 3), y, p] for t, y, p in tr]
    c.yaw_track = tr
    c.note = (c.note + f" [360 跟踪:{res.get('method')}]").strip()


def _focus_track(edl: EDL, project: Project, c: Clip) -> None:
    from ..fx.track import track_flat
    from ..media import probe

    src = Path(c.src) if Path(c.src).is_absolute() else project.root / c.src
    try:
        w, h = probe(src).display_size
        if not w or not h or w / h <= edl.width / edl.height * 1.1:
            return
        res = track_flat(src, c.in_, c.src_duration, w, h)
    except Exception:  # noqa: BLE001
        return
    tr = res.get("track") or []
    if tr:
        c.focus_track = [[round(c.src_to_timeline(c.in_ + t, 0.0), 3), x, y] for t, x, y in tr]
        c.note = (c.note + f" [主体构图:{res.get('method')}]").strip()


def _sfx(edl: EDL, project: Project, kind: str, t: float, vol: float, n: int, dur: float | None = None) -> None:
    from ..fx.sfx import get_sfx
    from ..edl import AudioItem
    from ..media import probe

    if not kind or t < 0 or t >= edl.total_duration:
        return
    p = get_sfx(kind, project.root / "cache" / "sfx", variant=n, dur=dur)
    d = dur or float(probe(p).duration or 0.6)
    d = min(d, edl.total_duration - t)
    edl.audio.append(AudioItem(kind="sfx", tag=kind, src=str(p), start=round(t, 3), duration=round(d, 3), volume=vol))


# ------------------------------------------------------------------ phase B
def plan_fx(edl: EDL, project: Project, style: dict, catalog: list[dict], marks: list[tuple[str, int, int]],
            sections: list[dict], track: dict | None, *, do_track: bool | None = None) -> list[str]:
    motion = style.get("motion") or {}
    fxs = style.get("fx") or {}
    sfx = style.get("sfx") or {}
    notes: list[str] = []
    pdata = project.load()
    hcfg = style.get("hud") or {}
    if not motion and not fxs and not hcfg:
        return notes
    if hcfg:
        from .hudplan import insert_terminal_card
        marks, tnote = insert_terminal_card(edl, project, style, marks)
        if tnote:
            notes.append(tnote)
    if do_track is None:
        do_track = (config.settings().get("track") or {}).get("detector", "auto") != "none"
    inten = float(motion.get("intensity", 0.6))
    tl = edl.timeline()
    total = edl.total_duration
    edl.beats, edl.downbeats = timeline_beats(track, total)
    edl.text_anims = {k: v for k, v in (style.get("text_anims") or {}).items() if v}
    edl.jianying = dict(style.get("jianying") or {})
    edl.look = [FX(**l) for l in (fxs.get("look") or []) if isinstance(l, dict) and l.get("type") in FX_TYPES]
    sec_start = {a for _, a, _ in marks}
    first_sec = marks[0][1] if marks else 0
    m2d = motion.get("moves_2d") or {}
    m360 = motion.get("moves_360") or {}
    pcfg = motion.get("punch") or {}
    portrait = edl.height > edl.width
    clip_units = [unit_for(c, catalog) or {} for c in edl.clips]
    acts = sorted([u.get("activity", 0.0) for u in clip_units]) or [0.0]
    hi_act = acts[int(0.7 * (len(acts) - 1))]
    n_tracked = 0
    for i, (c, (s, e)) in enumerate(zip(edl.clips, tl)):
        if c.generated:
            continue
        u = unit_for(c, catalog) or {}
        k = _h(c.id, c.media_id, c.in_, "fx")
        dur = c.duration
        # ---------------- camera move
        if c.projection == "equirect":
            if c.move is None or c.move.type not in MOVES_360:
                if i == first_sec and c.section in ("hook", "intro", "opening", marks[0][0] if marks else "") and dur >= 2.4:
                    mv = m360.get("hook", "planet_intro")
                else:
                    mv = m360.get(c.role) or m360.get("default", "follow")
                mv = _pick(mv, k) or "follow"
                params: dict = {}
                if mv == "orbit":
                    params = {"turns": 0.5 if dur < 4 else 1.0, "direction": "left" if k < 0.5 else "right"}
                if mv == "follow" and motion.get("whip360") and dur >= 3.5 and k > 0.55:
                    mv, params = "whip360", {"delta": round((120 + 60 * _h(c.id, "d")) * (1 if k > 0.77 else -1))}
                c.move = Move(type=mv if mv in MOVES_360 else "follow", params=params)
            if do_track and c.move.type in ("follow", "hero", "fixed360", "planet_intro", "whip360", "crystal_ball") \
                    and not c.yaw_track:
                _yaw_track(edl, project, c)
                n_tracked += 1
        else:
            if c.move is None:
                cand = m2d.get(c.role) or m2d.get("default") or []
                if c.role in PEOPLE and portrait and do_track:
                    _focus_track(edl, project, c)
                if (cand and k < float(motion.get("move_prob", 0.5))) or c.focus_track:
                    mv = _pick(cand, _h(c.id, "mv")) or ("subject" if c.focus_track else None)
                    if mv == "subject" and not c.focus_track:
                        mv = "push_in"
                    if mv == "punch":
                        mv = None
                        c.fx.append(FX(type="punch", intensity=round(min(1.0, 0.5 + 0.5 * inten), 2), params={"every": 1}))
                    if mv == "shake":
                        mv = None
                        c.fx.append(FX(type="shake", intensity=round(0.3 + 0.4 * inten, 2)))
                    if mv and mv in MOVES_2D:
                        prm = {"amount": round(0.06 + 0.1 * inten, 3)} if mv in ("push_in", "pull_out") else {}
                        if mv == "pan":
                            prm["direction"] = "left" if _h(c.id, "dir") < 0.5 else "right"
                        if mv == "roll":
                            prm["degrees"] = round(3 + 3 * inten, 1)
                        c.move = Move(type=mv, params=prm)
            elif portrait and c.role in PEOPLE and do_track and not c.focus_track:
                _focus_track(edl, project, c)
        # ---------------- beat punch-in
        if edl.beats and float(pcfg.get("prob", 0)) > 0 and c.role in set(pcfg.get("roles") or []) \
                and not any(f.type == "punch" for f in c.fx) and _h(c.id, "punch") < float(pcfg.get("prob", 0)):
            down = _at(pcfg, "beats") == "downbeats"
            c.fx.append(FX(type="punch", intensity=round(min(1.0, 0.45 + 0.5 * inten), 2),
                           params={"every": int(pcfg.get("every", 1)), "down": down}))
        sh = float(motion.get("shake", 0) or 0)
        if sh > 0 and c.role in ACTIONY and not any(f.type == "shake" for f in c.fx) and _h(c.id, "sh") < 0.6:
            c.fx.append(FX(type="shake", intensity=round(sh, 2), params={"on": "beats"} if edl.beats and sh >= 0.3 else {}))
        # ---------------- accent at section start / action peak
        accents = [a for a in (fxs.get("accents") or []) if a in FX_TYPES]
        adur = float(fxs.get("accent_dur", 0.4))
        if accents and i in sec_start and i > 0 and c.role not in PEOPLE:
            a = _pick(accents, _h(c.id, "acc"))
            c.fx.append(FX(type=a, start=0.0, dur=min(adur, dur * 0.5), intensity=round(0.5 + 0.4 * inten, 2)))
        elif accents and c.role not in PEOPLE and _h(c.id, "acc2") < float(fxs.get("accent_prob", 0)) * 0.6:
            a = _pick(accents, _h(c.id, "acc3"))
            st = max(0.0, dur - min(adur, dur * 0.4)) if a in ("glitch", "rgb_split", "flash") else 0.0
            c.fx.append(FX(type=a, start=round(st, 3), dur=round(min(adur, dur * 0.4), 3), intensity=round(0.45 + 0.4 * inten, 2)))
        peaks = [p for p in (fxs.get("peak") or []) if p in FX_TYPES]
        n_img = sum(1 for f in c.fx if f.type not in ("punch", "shake"))
        if peaks and u.get("activity", 0) >= hi_act > 0 and c.role in ACTIONY and dur >= 0.9 and n_img < (1 if dur < 1.5 else 2):
            pk = c.src_to_timeline(min(max(u.get("peak_t", c.in_), c.in_), c.out), 0.0)
            c.fx.append(FX(type=_pick(peaks, _h(c.id, "pk")), start=round(max(0.0, pk - 0.25), 3),
                           dur=round(min(0.9, dur - max(0.0, pk - 0.25)), 3), intensity=round(0.5 + 0.4 * inten, 2)))
        # ---------------- freeze callout
        if c.freeze and (motion.get("freeze") or {}).get("callout") and c.freeze.text:
            t0 = s + c.freeze.at
            edl.overlays.append(TextOverlay(start=round(t0 + 0.05, 3), end=round(t0 + c.freeze.hold, 3), text=c.freeze.text,
                                            kind="callout", anim=edl.text_anims.get("callout", "pop"),
                                            x=0.27, y=0.24, target=[0.52, 0.52]))
    # ---------------- whip-pan between consecutive 360 shots (heading change)
    if motion.get("whip360"):
        for i in range(1, len(edl.clips)):
            a, b = edl.clips[i - 1], edl.clips[i]
            if a.projection == b.projection == "equirect" and b.transition_in.type in ("cut", "fade", "dissolve"):
                b.transition_in = Transition(type="whip_left" if _h(b.id, "w") < 0.5 else "whip_right", duration=0.35)
    # ---------------- PIP: maker talking + demo picture-in-picture
    if motion.get("pip") and pdata.get("type") == "maker":
        demos = sorted([u for u in catalog if u["category"] in ("screen", "product", "build", "detail")],
                       key=lambda u: -u["highlight"])
        used = set()
        for c in edl.clips:
            if c.role in ("talking_head", "interview") and c.duration >= 4.0 and c.pip is None and demos:
                d = next((u for u in demos if u["uid"] not in used and u["duration"] >= min(c.src_duration, 3.0)), None)
                if d:
                    used.add(d["uid"])
                    c.pip = PIP(src=d["path"], media_id=d["media_id"], **{"in": d["start"]}, layout="pip_br",
                                projection=d.get("projection", "flat"))
    edl.normalize_transitions()
    tl = edl.timeline()
    total = edl.total_duration
    # ---------------- white flashes on downbeats / section changes
    bf = fxs.get("beat_flash") or {}
    if _at(bf) in ("beats", "downbeats") and edl.beats:
        src = edl.downbeats if _at(bf) == "downbeats" and edl.downbeats else edl.beats
        every = max(1, int(bf.get("every", 1)))
        last = -9.0
        for j, b in enumerate(src[::every]):
            ci = _clip_at(tl, b)
            if ci is None or edl.clips[ci].role in PEOPLE or b - last < 1.2:
                continue
            edl.flashes.append([round(b, 3), round(float(bf.get("strength", 0.5)), 2)])
            last = b
    # ---------------- tracker HUD windows (after transitions are final: the lock sits on a beat / action peak)
    if hcfg:
        from .hudplan import plan_hud_sfx, plan_tracker_hud
        notes += plan_tracker_hud(edl, project, style, catalog, tl)
    # ---------------- SFX
    if hcfg and (config.settings().get("sfx") or {}).get("enabled", True):
        from .hudplan import plan_hud_sfx
        hv = float(hcfg.get("sfx_volume", (sfx or {}).get("volume", 0.5)))
        nh = plan_hud_sfx(edl, project, style, tl, hv)
        if nh:
            notes.append(f"HUD 音效 {nh} 个（键盘声 / 锁定提示音 / 故障切换 / 收束 chime，程序合成，-14 LUFS）。")
    if (config.settings().get("sfx") or {}).get("enabled", True) and sfx:
        vol = float(sfx.get("volume", (config.settings().get("sfx") or {}).get("volume", 0.5)))
        n = 0
        placed: list[float] = []

        def free(t, gap=0.3):
            return all(abs(t - p) >= gap for p in placed)

        sec_kinds = [x for x in (sfx.get("section") or []) if x]
        for i, c in enumerate(edl.clips):
            if i == 0:
                continue
            t0 = tl[i][0]
            tr = c.transition_in
            if i in sec_start and sec_kinds:
                if "riser" in sec_kinds and t0 > 1.4 and free(t0 - 0.6, 1.5) and edl.clips[i - 1].role not in PEOPLE:
                    _sfx(edl, project, "riser", t0 - 1.2, vol * 0.7, n, 1.2); n += 1
                hit = next((x for x in sec_kinds if x != "riser"), None)
                if hit:
                    _sfx(edl, project, hit, t0 + tr.duration / 2 - 0.02, vol, n); n += 1
                placed.append(t0 + tr.duration / 2)
            elif tr.type != "cut":
                kind = sfx.get("custom_transition") if tr.is_custom else sfx.get("transition")
                if tr.type == "glitch":
                    kind = sfx.get("glitch") or kind
                t = t0 + tr.duration / 2 - (0.25 if kind in ("whoosh", "swish") else 0.0)
                if kind and free(t):
                    _sfx(edl, project, kind, max(0.0, t), vol * 0.8, n); n += 1
                    placed.append(t)
            for f in c.fx:
                if f.type == "glitch" and sfx.get("glitch") and free(tl[i][0] + f.start):
                    _sfx(edl, project, sfx["glitch"], tl[i][0] + f.start, vol * 0.6, n, min(0.5, f.dur or 0.4)); n += 1
                    placed.append(tl[i][0] + f.start)
            if c.freeze and sfx.get("freeze"):
                _sfx(edl, project, sfx["freeze"], tl[i][0] + c.freeze.at, vol * 0.8, n); n += 1
        if sfx.get("flash"):
            for t, st in edl.flashes:
                if st >= 0.45 and free(t, 0.5):
                    _sfx(edl, project, sfx["flash"], max(0.0, t - 0.02), vol * 0.6, n); n += 1
                    placed.append(t)
        if n:
            notes.append(f"自动音效 {n} 个（{'本地音效库' if (config.settings().get('sfx') or {}).get('library') else '程序合成'}）。")
    # ---------------- progress bar
    pg = style.get("progress") or {}
    if pg.get("enabled") and len(marks) >= 3 and total >= 20:
        names = {s["id"]: s.get("name", s["id"]) for s in sections}
        edl.progress = {"color": pg.get("color", "#3DD6F5"), "height": int(pg.get("height", 6)), "position": "bottom",
                        "chapters": [[tl[a][0], names.get(sid, sid)] for sid, a, _ in marks]}
    nm = sum(1 for c in edl.clips if c.move and c.move.type != "none")
    nf = sum(len(c.fx) for c in edl.clips)
    notes.append(f"运镜/特效（{style.get('name')}，力度 {inten:.1f}）：{nm} 个运镜、{nf} 个特效窗口、"
                 f"{len(edl.flashes)} 个卡点白闪、{sum(1 for c in edl.clips if c.transition_in.is_custom)} 个自定义转场"
                 + (f"、360 跟踪 {n_tracked} 段" if n_tracked else "") + "。")
    return notes


def sanitize_llm_clip_fx(c: Clip, raw: dict) -> None:
    """Validate the optional v2 fields an LLM may propose for one clip (unknown names are dropped)."""
    mv = raw.get("move")
    if isinstance(mv, str):
        mv = {"type": mv}
    if isinstance(mv, dict) and mv.get("type") in (MOVES_360 if c.projection == "equirect" else MOVES_2D):
        prm = mv.get("params") if isinstance(mv.get("params"), dict) else {}
        c.move = Move(type=mv["type"], params={k: v for k, v in prm.items() if isinstance(v, (int, float, str))})
    for f in raw.get("fx") or []:
        if isinstance(f, str):
            f = {"type": f}
        if not isinstance(f, dict) or f.get("type") not in FX_TYPES:
            continue
        try:
            st = max(0.0, min(float(f.get("start", 0) or 0), c.duration - 0.1))
            d = f.get("dur")
            d = None if d is None else max(0.1, min(float(d), c.duration - st))
            it = max(0.0, min(1.0, float(f.get("intensity", 0.6))))
        except (TypeError, ValueError):
            continue
        prm = {"on": "beats"} if f.get("on") == "beats" else {}
        if f["type"] == "lens_look":
            from ..fx.lens import PALETTES
            if f.get("palette") in PALETTES:
                prm["palette"] = f["palette"]
        if f["type"] == "tracker_hud":
            if isinstance(f.get("label"), str):
                prm["label"] = f["label"][:16]
            lk = [round(float(x), 3) for x in (f.get("locks") or []) if isinstance(x, (int, float)) and 0 <= x <= c.duration]
            if lk:
                prm["locks"] = lk[:3]
        c.fx.append(FX(type=f["type"], start=round(st, 3), dur=d, intensity=it, params=prm))
    if raw.get("ramp") and c.role not in PEOPLE and c.src_duration >= 1.5:
        c.ramp = Ramp()
    fz = raw.get("freeze")
    if fz and c.src_duration >= 1.2:
        txt = fz if isinstance(fz, str) else (fz.get("text", "") if isinstance(fz, dict) else "")
        c.freeze = Freeze(at=round(c.base_duration * 0.5, 3), hold=1.0, text=str(txt)[:12])


def llm_vocab() -> str:
    def j(d):
        return "、".join(f"{k}({v.split('（')[0]})" for k, v in d.items())
    return (f"360 运镜（仅 360 素材）：{j(MOVES_360)}\n平面运镜：{j(MOVES_2D)}\n"
            f"特效（fx 窗口，start/dur 为片段内秒）：{j(FX_TYPES)}\n自定义转场：{j(CUSTOM_TRANSITIONS)}\n"
            "HUD：tracker_hud 可带 locks=[锁定瞬间的片段内秒]、label；lens_look 可带 palette（paper/thermal/mono/phosphor/amber/navy/neon）。"
            "适合产品/细节/屏幕/演示镜头，不要用在口播上。终端插卡（terminal_hud）由风格的 hud.terminal 自动生成，不用你输出。")
