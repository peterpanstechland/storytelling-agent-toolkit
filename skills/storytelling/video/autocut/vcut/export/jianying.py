"""剪映专业版 draft export via pyJianYingDraft (optional extra `jianying`).

Compatibility (pyJianYingDraft 0.3.0, 2026-07): generated drafts are plain JSON and are reported by
upstream to open in 剪映 5.9 and 10.8. Newer 剪映 encrypts *its own* draft_content.json, which only
matters for reading/templating existing drafts (not used here). Auto-export via UI automation only
works on 剪映 ≤6 and is not used.
"""
from __future__ import annotations

import datetime as _dt
import sys
from pathlib import Path

from .. import config
from ..edl import EDL, JIANYING_TRANSITION, Clip
from .jianying_fx import FLASH_FX, SCENE_FX, TEXT_ANIM, Resolver, move_keyframes
from ..project import Project
from ..util import ok, slugify, warn
from .timemap import nle_layout, ramp_parts, remap

SEC = 1_000_000


def jianying_available() -> bool:
    try:
        import pyJianYingDraft  # noqa: F401
        return True
    except Exception:  # noqa: BLE001 (uiautomation import problems on some Windows Pythons)
        return False


def _hex_rgb(h: str) -> tuple[float, float, float]:
    h = (h or "#FFFFFF").lstrip("#")
    try:
        return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))  # type: ignore[return-value]
    except ValueError:
        return (1.0, 1.0, 1.0)


def _us(t: float) -> int:
    return int(round(t * SEC))


def needs_bake(c: Clip) -> bool:
    """剪映 cannot do these natively → bake the geometry (no colour/effects) into a mezzanine clip."""
    from ..edl import HUD_FX
    return bool(c.projection == "equirect" or c.ramp or c.freeze or c.pip or c.generated
                or any(f.type in HUD_FX for f in c.fx))


def bake_clip(project: Project, edl: EDL, c: Clip, clip_start: float, out_dir: Path) -> Path:
    """Render only the geometry of a clip (360 reframe / speed ramp / freeze / PIP) — effects, look, colour
    and volume stay native & editable in 剪映."""
    from ..fx.engine import render_clip
    from ..media import pick_encoder
    from ..util import short_hash

    from ..edl import HUD_FX
    clean = c.model_copy(update={"fx": [f for f in c.fx if f.type in HUD_FX], "volume": 1.0})   # tracker_hud / lens_look stay baked in
    e2 = edl.model_copy(update={"look": []})
    key = short_hash(clean.model_dump_json(), e2.width, e2.height, e2.fps, n=12)
    out = out_dir / f"{c.id}_{key}.mp4"
    if not out.exists():
        out_dir.mkdir(parents=True, exist_ok=True)
        render_clip(project, e2, clean, clip_start, out, e2.width, e2.height, e2.fps, quick=False,
                    encoder=pick_encoder((config.settings().get("render") or {}).get("encoder", "auto")),
                    lut_name="", color_filter="", cwd=out_dir)
    return out


def _beats_local(edl: EDL, start: float, dur: float, every: int = 1, down: bool = False) -> list[float]:
    src = edl.downbeats if down and edl.downbeats else edl.beats
    return [round(b - start, 3) for b in src[::max(1, every)] if start <= b < start + dur]


def export_jianying(project: Project, edl: EDL, drafts_dir: Path | None = None, name: str | None = None) -> Path:
    import pyJianYingDraft as jy
    from pyJianYingDraft import ClipSettings, KeyframeProperty, TextStyle, Timerange, TrackSpec, TrackType, TransitionType

    R = Resolver()
    jcfg = dict(edl.jianying or {})
    scene_map = {**SCENE_FX, **(jcfg.get("scene_effects") or {})}

    target = drafts_dir or config.jianying_drafts_dir()
    if target is None or not Path(target).is_dir():
        if target is not None:
            warn(f"剪映草稿目录不存在：{target}，先导出到项目 drafts/jianying/，之后手动复制。")
        target = project.drafts_dir / "jianying"
    target = Path(target)
    target.mkdir(parents=True, exist_ok=True)
    name = name or f"vcut_{slugify(edl.project or project.root.name)}_{_dt.datetime.now():%m%d_%H%M}"
    folder = jy.DraftFolder(str(target))
    script = folder.create_draft(name, edl.width, edl.height, edl.fps, allow_replace=True)
    has_logo = bool(edl.logo and Path(edl.logo.src).exists())
    layout = nle_layout(edl)
    total = layout[-1][1] if layout else 0.0
    # sfx may overlap → greedy lanes
    sfx_lanes: list[float] = []
    sfx_items = []
    for a in sorted([a for a in edl.audio if a.kind == "sfx" and Path(a.src).exists()], key=lambda a: a.start):
        st = remap(edl, a.start)
        lane = next((i for i, end in enumerate(sfx_lanes) if end <= st), None)
        if lane is None:
            sfx_lanes.append(0.0)
            lane = len(sfx_lanes) - 1
        sfx_lanes[lane] = st + a.duration
        sfx_items.append((a, st, lane))
    # effect windows (fx + accents) on the timeline; overlapping windows → extra effect tracks
    fx_windows = []
    for c, (s, _e) in zip(edl.clips, layout):
        for f in c.fx:
            if f.type in ("punch",) or (f.type == "shake" and not scene_map.get("shake")):
                continue
            if f.type == "shake":
                continue  # shake → keyframes on the clip (more faithful than the 抖动 effect)
            name_ = scene_map.get(f.type)
            if not name_:
                continue
            d = (f.dur if f.dur is not None else c.duration - f.start)
            if d >= 0.1:
                fx_windows.append((s + f.start, min(d, c.duration - f.start), name_, f.type))
    fx_lanes: list[float] = []
    fx_items = []
    for st, d, nm, ft in sorted(fx_windows):
        lane = next((i for i, end in enumerate(fx_lanes) if end <= st + 1e-3), None)
        if lane is None:
            fx_lanes.append(0.0)
            lane = len(fx_lanes) - 1
        fx_lanes[lane] = st + d
        fx_items.append((st, d, nm, ft, lane))
    looks = [(scene_map.get(l.type), l) for l in edl.look if scene_map.get(l.type)]
    flt = jcfg.get("filter") or ""
    specs = [
        (any(a.kind == "music" for a in edl.audio), TrackSpec(TrackType.audio, "music")),
        (any(a.kind == "voiceover" for a in edl.audio), TrackSpec(TrackType.audio, "voiceover")),
        *[(True, TrackSpec(TrackType.audio, f"sfx{i + 1}")) for i in range(len(sfx_lanes))],
        (True, TrackSpec(TrackType.video, "main")),
        (has_logo, TrackSpec(TrackType.video, "logo")),
        (bool(flt), TrackSpec(TrackType.filter, "filter")),
        *[(True, TrackSpec(TrackType.effect, f"look{i + 1}")) for i in range(len(looks))],
        *[(True, TrackSpec(TrackType.effect, f"fx{i + 1}")) for i in range(len(fx_lanes))],
        (bool(edl.flashes), TrackSpec(TrackType.effect, "flash")),
        (bool(edl.subtitles), TrackSpec(TrackType.text, "subtitle")),
        (bool(edl.overlays), TrackSpec(TrackType.text, "titles")),
    ]
    script.append_tracks([spec for need, spec in specs if need])  # order = background → foreground
    notes: list[str] = []
    materials: dict[str, object] = {}

    def vmat(p: str):
        if p not in materials:
            materials[p] = jy.VideoMaterial(p)
        return materials[p]

    segs = []
    bake_dir = project.drafts_dir / "jianying_media"
    n_baked = 0
    tl = edl.timeline()
    for ci, (c, (s, _e)) in enumerate(zip(edl.clips, layout)):
        src = Path(c.src)
        src = str((src if src.is_absolute() else project.root / src).resolve())
        t = s
        baked = needs_bake(c)
        if baked:
            try:
                src = str(bake_clip(project, edl, c, tl[ci][0], bake_dir).resolve())
                mdur = vmat(src).duration / SEC  # encoded length can be a frame shorter than planned
                parts = [(0.0, min(c.duration, mdur), 1.0)]
                n_baked += 1
            except Exception as e:  # noqa: BLE001
                if c.generated:
                    notes.append(f"生成片段 {c.id}（{c.generated.get('type')}）预渲染失败（{e}），草稿里已跳过。")
                    continue
                notes.append(f"片段 {c.id} 预渲染失败（{e}），草稿里用原始素材代替（无 360 重构图/变速曲线/定格/追踪框 HUD/镜头质感）。")
                baked = False
        if not baked:
            parts = ramp_parts(c)
        src_ar = None
        if not baked and c.projection != "equirect":
            try:
                from ..media import probe
                w_, h_ = probe(Path(src)).display_size
                src_ar = w_ / h_ if w_ and h_ else None
            except Exception:  # noqa: BLE001
                src_ar = None
        for k, (a, b, sp) in enumerate(parts):
            d = (b - a) / sp
            seg = jy.VideoSegment(vmat(src), Timerange(_us(t), _us(d)), source_timerange=Timerange(_us(a), _us(b - a)),
                                  volume=max(0.0, min(2.0, c.volume)))
            if ("zoom_in" in c.effects or "zoom_out" in c.effects) and k == 0:
                z0, z1 = (1.0, 1.1) if "zoom_in" in c.effects else (1.1, 1.0)
                seg.add_keyframe(KeyframeProperty.uniform_scale, 0, z0)
                seg.add_keyframe(KeyframeProperty.uniform_scale, _us(d) - 1, z1)
            elif k == 0 and len(parts) == 1:
                punch = next((f for f in c.fx if f.type == "punch"), None)
                bl = _beats_local(edl, tl[ci][0], c.duration, int((punch.params or {}).get("every", 1)) if punch else 1,
                                  bool((punch.params or {}).get("down")) if punch else False)
                cc = c if not baked else c.model_copy(update={"move": None, "focus_track": []})
                for prop, tk, val in move_keyframes(cc, d, bl, edl.width, edl.height, src_ar):
                    seg.add_keyframe(getattr(KeyframeProperty, prop), _us(max(0.0, min(tk, d - 0.001))), val)
            segs.append((seg, c, k))
            t += d
    # clip intro/outro animations from the style (first clip of the film and of each section; last clip outro)
    intro_t = R.resolve("intro", jcfg.get("intro")) if jcfg.get("intro") else None
    outro_t = R.resolve("outro", jcfg.get("outro")) if jcfg.get("outro") else None
    sec_first = {i for i, c in enumerate(edl.clips) if i == 0 or c.section != edl.clips[i - 1].section}
    for seg, c, k in segs:
        i = edl.clips.index(c)
        if intro_t is not None and k == 0 and i in sec_first and c.transition_in.type == "cut" and c.duration >= 1.2:
            seg.add_animation(intro_t, _us(min(0.5, c.duration / 3)))
    if outro_t is not None and segs and segs[-1][1].duration >= 1.5:
        segs[-1][0].add_animation(outro_t, _us(0.6))
    # transitions are attached to the *previous* segment
    for i in range(1, len(segs)):
        seg, c, k = segs[i]
        if k != 0 or c.transition_in.type == "cut":
            continue
        jname = JIANYING_TRANSITION.get(c.transition_in.type, jcfg.get("transition") or "叠化")
        tt = R.resolve("transition", jname) or TransitionType.叠化
        prev = segs[i - 1][0]
        dur = _us(max(0.1, c.transition_in.duration))
        prev.add_transition(tt, duration=dur)
    for seg, _, _ in segs:
        script.add_segment(seg, "main")

    # style filter over the whole timeline, look effects, effect windows, beat flashes
    if flt and total > 0:
        ft = R.resolve("filter", flt)
        if ft is not None:
            script.add_filter(ft, Timerange(0, _us(total)), "filter", intensity=float(jcfg.get("filter_intensity", 60)))
    for i, (nm, l) in enumerate(looks):
        et = R.resolve("scene", nm)
        if et is not None and total > 0:
            script.add_effect(et, Timerange(0, _us(total)), f"look{i + 1}")
    for st, d, nm, _ft, lane in fx_items:
        et = R.resolve("scene", nm)
        if et is not None:
            script.add_effect(et, Timerange(_us(st), _us(d)), f"fx{lane + 1}")
    if edl.flashes:
        et = R.resolve("scene", (jcfg.get("scene_effects") or {}).get("flash") or FLASH_FX)
        last = -1.0
        for t_, _st in edl.flashes:
            st = remap(edl, t_)
            if et is None or st < last + 0.05 or st + 0.25 > total:
                continue
            script.add_effect(et, Timerange(_us(st), _us(0.25)), "flash")
            last = st + 0.25
    speech = []
    for c, (s, e) in zip(edl.clips, layout):
        if c.role in ("talking_head", "interview") and c.volume >= 0.5:
            speech.append((s, e))

    for a, st, lane in sfx_items:
        mat = jy.AudioMaterial(a.src)
        d = min(a.duration, mat.duration / SEC, total - st)
        if d > 0.05:
            script.add_segment(jy.AudioSegment(mat, Timerange(_us(st), _us(d)), source_timerange=Timerange(0, _us(d)),
                                               volume=a.volume), f"sfx{lane + 1}")
    for a in edl.audio:
        src = a.src.split("#")[0]
        if a.kind == "sfx" or not Path(src).exists():
            continue
        start = remap(edl, a.start)
        dur = min(a.duration, total - start) if a.kind == "music" else a.duration
        if dur <= 0.05:
            continue
        mat = jy.AudioMaterial(src)
        mlen = mat.duration / SEC
        pos, off = start, a.in_
        first = True
        while pos < start + dur - 0.05:
            piece = min(start + dur - pos, max(0.1, mlen - off))
            seg = jy.AudioSegment(mat, Timerange(_us(pos), _us(piece)), source_timerange=Timerange(_us(off), _us(piece)),
                                  volume=a.volume)
            if first and a.fade_in or (pos + piece >= start + dur - 0.05 and a.fade_out):
                seg.add_fade(_us(a.fade_in if first else 0), _us(a.fade_out if pos + piece >= start + dur - 0.05 else 0))
            if a.kind == "music" and a.duck:
                for s0, e0 in speech:
                    if e0 <= pos or s0 >= pos + piece:
                        continue
                    for tt_, vv in ((s0 - 0.25, a.volume), (s0, a.volume * 0.35), (e0, a.volume * 0.35), (e0 + 0.35, a.volume)):
                        if pos <= tt_ <= pos + piece:
                            seg.add_keyframe(_us(tt_ - pos), vv)
            script.add_segment(seg, "music" if a.kind == "music" else "voiceover")
            if a.kind == "sfx":
                break
            pos += piece
            off = 0.0
            first = False
            if not a.loop:
                break

    if has_logo:
        pos = {"top_right": (0.82, 0.82), "top_left": (-0.82, 0.82), "bottom_right": (0.82, -0.82),
               "bottom_left": (-0.82, -0.82)}[edl.logo.position]
        lmat = jy.VideoMaterial(edl.logo.src)
        end = remap(edl, edl.logo.end) if edl.logo.end is not None else total
        lseg = jy.VideoSegment(lmat, Timerange(_us(remap(edl, edl.logo.start)), _us(end - remap(edl, edl.logo.start))),
                               clip_settings=ClipSettings(scale_x=edl.logo.scale * 1.6, scale_y=edl.logo.scale * 1.6,
                                                          transform_x=pos[0], transform_y=pos[1], alpha=edl.logo.opacity))
        script.add_segment(lseg, "logo")

    ss, ts = edl.subtitle_style or {}, edl.title_style or {}
    sub_style = TextStyle(size=7.0 if edl.height > edl.width else 6.0, color=_hex_rgb(ss.get("primary", "#FFFFFF")),
                          bold=bool(ss.get("bold")), align=1, auto_wrapping=True, max_line_width=0.82)
    for q in edl.subtitles:
        s0, s1 = remap(edl, q.start), remap(edl, q.end)
        if s1 - s0 < 0.1:
            continue
        script.add_segment(jy.TextSegment(q.text, Timerange(_us(s0), _us(s1 - s0)), style=sub_style,
                                          border=jy.TextBorder(color=(0, 0, 0), width=40.0),
                                          clip_settings=ClipSettings(transform_y=-0.78)), "subtitle")
    ypos = {"title": 0.0, "section": 0.72, "lower_third": -0.45, "caption": -0.5, "cta": -0.3, "callout": 0.5}
    sizes = {"title": 13.0, "section": 9.0, "lower_third": 7.0, "caption": 7.5, "cta": 9.0, "callout": 8.0}
    text_defaults = dict(edl.text_anims or {})

    def text_anim(seg, kind: str, anim: str, dur: float) -> None:
        preset = TEXT_ANIM.get(anim or text_defaults.get(kind, ""))
        if not preset:
            return
        tin, tout, tloop = preset
        if kind == "title" and jcfg.get("text_intro"):
            tin = jcfg["text_intro"]
        if jcfg.get("text_outro"):
            tout = jcfg["text_outro"]
        if kind in ("title", "section") and jcfg.get("text_loop"):
            tloop = jcfg["text_loop"]
        di = min(0.5, dur / 3)
        a_in = R.resolve("text_intro", tin)
        a_out = R.resolve("text_outro", tout) if dur >= 1.2 else None
        if a_in is not None:
            seg.add_animation(a_in, _us(di))
        if a_out is not None:
            seg.add_animation(a_out, _us(min(0.4, dur / 4)))
        if tloop and dur >= 2.0:
            a_loop = R.resolve("text_loop", tloop)
            if a_loop is not None:
                seg.add_animation(a_loop)
    last_end = 0.0
    for o in sorted(edl.overlays, key=lambda o: o.start):
        s0, s1 = remap(edl, o.start), remap(edl, o.end)
        s0 = max(s0, last_end)  # one text track: no overlaps allowed
        if s1 - s0 < 0.2:
            notes.append(f"屏幕文字“{o.text}”与其它文字重叠，未放入草稿。")
            continue
        st = TextStyle(size=sizes.get(o.kind, 8.0), bold=True, align=1,
                       color=_hex_rgb(ts.get("primary", "#FFFFFF")), auto_wrapping=True)
        tx = -0.45 if o.kind == "lower_third" else 0.0
        ty = ypos.get(o.kind, 0.0)
        if o.x is not None and o.y is not None:
            tx, ty = (o.x - 0.5) * 2, (0.5 - o.y) * 2
        tseg = jy.TextSegment(o.text, Timerange(_us(s0), _us(s1 - s0)), style=st,
                              border=jy.TextBorder(color=(0, 0, 0), width=30.0),
                              clip_settings=ClipSettings(transform_y=ty, transform_x=tx))
        text_anim(tseg, o.kind, o.anim, s1 - s0)
        script.add_segment(tseg, "titles")
        last_end = s1
    script.save()
    out = target / name
    readme = out / "vcut_说明.txt"
    lines = [
        f"由 storytelling autocut 生成：{_dt.datetime.now():%Y-%m-%d %H:%M}",
        f"项目：{project.root}",
        "调色用剪映滤镜近似风格调色；特效用剪映「场景特效」近似（故障/色差/漏光/闪白…），运镜用关键帧近似；",
        "360° 重构图、变速曲线、定格、画中画无法用剪映原生功能表达，已预渲染为 drafts/jianying_media/ 下的片段"
        f"（{n_baked} 段，只含画面运动，不含调色/特效，后两者仍可在剪映里调整）。",
        "字幕样式、ducking 为近似还原；以 renders/ 里的 FFmpeg 预览为准微调。",
        "如果剪映列表里看不到这个草稿：确认文件夹在剪映 设置→草稿位置 下，然后重启剪映。",
        *sorted(set(notes + R.notes)),
        *R.summary(),
    ]
    readme.write_text("\n".join(lines), encoding="utf-8")
    if sys.platform != "win32":
        notes.append("当前不是 Windows：草稿里的素材路径是本机路径，换到 Windows 后需要在 Windows 上重新运行 `autocut draft`。")
    for n in sorted(set(notes + R.notes)):
        warn(n)
    ok(f"剪映草稿：{out}")
    return out
