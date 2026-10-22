"""Render an EDL to MP4 with FFmpeg.

Pass 1  each clip -> normalized mezzanine (trim, speed/ramp, reframe to W×H, fps, color, zoom) — cached.
Pass 2  one filter graph: concat / xfade chain, letterbox, logo, ASS text (titles + subtitles),
        voiceover + music with sidechain ducking under speech, loudness normalization, final encode
        (NVENC when it really works, else libx264).
"""
from __future__ import annotations

import math
import os
import shutil
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import config
from .edl import EDL, RAMP_FACTOR, RAMP_SPLIT, XFADE, Clip
from .media import FFmpegError, compatible_xfade, ffmpeg, file_option, kind_of, pick_encoder, probe, video_encode_args
from .project import Project
from .util import info, ok, short_hash, warn

ENGINE_TR_VERSION = "2.0.2"

# ----------------------------------------------------------------- helpers


def default_font() -> str:
    if sys.platform == "win32":
        return "Microsoft YaHei"
    if sys.platform == "darwin":
        return "PingFang SC"
    return "Noto Sans CJK SC"


def ass_color(hex_rgb: str, alpha: int = 0) -> str:
    h = (hex_rgb or "#FFFFFF").lstrip("#")
    if len(h) != 6:
        h = "FFFFFF"
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f"&H{alpha:02X}{b}{g}{r}".upper()


def ass_time(t: float) -> str:
    t = max(0.0, t)
    h = int(t // 3600)
    m = int(t % 3600 // 60)
    s = t % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def srt_time(t: float) -> str:
    t = max(0.0, t)
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def ass_escape(text: str) -> str:
    return text.replace("\\", "＼").replace("{", "｛").replace("}", "｝").replace("\n", "\\N")


def measure_lufs(path: Path) -> float | None:
    """Integrated loudness via ebur128 (audio-only decode, fast)."""
    import re
    proc = ffmpeg(["-i", str(path), "-vn", "-af", "ebur128=framelog=quiet", "-f", "null", "-"], check=False)
    txt = (proc.stderr or b"").decode("utf-8", "replace")
    m = re.findall(r"I:\s+(-?[\d.]+) LUFS", txt)
    return float(m[-1]) if m else None


def _fix_loudness(path: Path, target: float, rcfg: dict, work: Path) -> None:
    """Single-pass loudnorm often lands 1-3 LU low on short mixes; apply a linear gain + limiter (video stream copied)."""
    got = measure_lufs(path)
    if got is None or got < -60 or abs(got - target) <= 0.7:
        return
    gain = max(-12.0, min(12.0, target - got))
    fixed = path.with_name(path.stem + ".lufs.mp4")
    ffmpeg(["-i", str(path), "-map", "0:v", "-map", "0:a", "-c:v", "copy",
            "-af", f"volume={gain:.2f}dB,alimiter=limit=0.84:level=false,aresample=48000",
            "-c:a", "aac", "-b:a", str(rcfg.get("audio_bitrate", "192k")), "-movflags", "+faststart", str(fixed)])
    fixed.replace(path)
    info(f"响度校正：{got:.1f} → 目标 {target:.0f} LUFS（{gain:+.1f} dB）")


def write_srt(edl: EDL, path: Path) -> Path:
    lines = []
    for i, c in enumerate(edl.subtitles, 1):
        lines += [str(i), f"{srt_time(c.start)} --> {srt_time(c.end)}", c.text, ""]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _chunks(text: str) -> list[str]:
    """Kinetic chunks: words for Latin text, 2-character groups for CJK runs (punctuation sticks to the left)."""
    import re
    if re.search(r"[\u4e00-\u9fff]", text):
        out: list[str] = []
        for tok in re.findall(r"[\u4e00-\u9fff]+|[A-Za-z0-9][A-Za-z0-9.+\-_']*|\s+|[^\sA-Za-z0-9\u4e00-\u9fff]+", text):
            if re.fullmatch(r"[\u4e00-\u9fff]+", tok):
                out += [tok[i:i + 2] for i in range(0, len(tok), 2)]
            elif out and (tok.isspace() or not re.match(r"[A-Za-z0-9]", tok)):
                out[-1] += tok
            else:
                out.append(tok)
        return out or [text]
    return [w + " " for w in text.split(" ")] if " " in text else [text]


def ass_anim_events(text: str, anim: str, style: str, an: int, x: float, y: float, start: float, end: float,
                    W: int, H: int, layer: int = 1, accent_hex: str = "#3DD6F5") -> list[str]:
    """Kinetic typography presets as ASS override tags (rendered by libass in the preview)."""
    t0, t1 = ass_time(start), ass_time(end)
    D = int(max(0.2, end - start) * 1000)
    txt = ass_escape(text)
    pos = f"\\an{an}\\pos({x:.0f},{y:.0f})"
    ev = lambda tags, body, lay=layer, a=t0, b=t1: f"Dialogue: {lay},{a},{b},{style},,0,0,0,,{{{tags}}}{body}"  # noqa: E731
    if anim == "pop":
        return [ev(pos + "\\fscx30\\fscy30\\alpha&HFF&\\t(0,110,\\alpha&H00&)\\t(0,200,\\fscx114\\fscy114)"
                   "\\t(200,330,\\fscx100\\fscy100)\\fad(0,220)", txt)]
    if anim == "slide_up":
        dy = H * 0.06
        return [ev(f"\\an{an}\\move({x:.0f},{y + dy:.0f},{x:.0f},{y:.0f},0,380)\\blur6\\t(0,380,\\blur0)\\fad(220,220)", txt)]
    if anim == "stamp":
        return [ev(pos + "\\fscx260\\fscy260\\alpha&HFF&\\blur8\\frz-7\\t(0,170,\\fscx100\\fscy100\\alpha&H00&\\blur0\\frz-2)"
                   "\\t(170,250,\\fscx107\\fscy107)\\t(250,340,\\fscx100\\fscy100)\\fad(0,220)", txt)]
    if anim == "typewriter":
        chars = list(text)
        step = max(25, min(70, int(min(D * 0.5, 1400) / max(1, len(chars)))))
        body = "".join(f"{{\\alpha&HFF&\\t({k * step},{k * step + 1},\\alpha&H00&)}}{ass_escape(ch)}" for k, ch in enumerate(chars))
        return [ev(pos + "\\fad(0,200)", body)]
    if anim == "kinetic":
        parts = _chunks(text)
        step = max(60, min(160, int(min(D * 0.6, 1600) / max(1, len(parts)))))
        body = "".join(f"{{\\alpha&HFF&\\fscx55\\fscy55\\t({k * step},{k * step + 140},\\alpha&H00&\\fscx100\\fscy100)}}{ass_escape(w)}"
                       for k, w in enumerate(parts))
        return [ev(pos + "\\fad(0,200)", body)]
    if anim == "glitch":
        g_end = ass_time(min(end, start + 0.55))
        jit = "\\t(0,60,\\fax0.25)\\t(60,120,\\fax-0.2)\\t(120,180,\\fax0.1)\\t(180,240,\\fax0)"
        dx = max(4, W // 300)
        return [
            ev(pos + "\\alpha&HFF&\\t(40,41,\\alpha&H00&)\\t(90,91,\\alpha&HFF&)\\t(130,131,\\alpha&H00&)" + jit + "\\fad(0,220)", txt),
            ev(f"\\an{an}\\pos({x + dx:.0f},{y:.0f})\\1c&H0000FF&\\bord0\\shad0\\alpha&H60&" + jit, txt, layer - 1 if layer > 0 else 0, t0, g_end),
            ev(f"\\an{an}\\pos({x - dx:.0f},{y + dx / 2:.0f})\\1c&HFFFF00&\\bord0\\shad0\\alpha&H60&" + jit, txt, layer - 1 if layer > 0 else 0, t0, g_end),
        ]
    if anim == "highlight_box":
        x_from = x if an in (1, 4, 7) else 0
        return [ev(pos + f"\\clip({x_from:.0f},0,{x_from + 1:.0f},{H})\\t(0,380,\\clip({x_from:.0f},0,{W},{H}))\\fad(0,220)", txt)]
    return [ev(pos + ("\\fad(400,400)\\blur1" if style == "Title" else "\\fad(250,250)"), txt)]


def ass_callout_marker(x: float, y: float, tx: float, ty: float, start: float, end: float, base: int, accent_hex: str) -> list[str]:
    """Leader line from the callout box to the target + a pulsing ring at the target."""
    col = ass_color(accent_hex)
    th = max(2.0, base / 360)
    dx, dy = tx - x, ty - y
    L = math.hypot(dx, dy) or 1.0
    nx, ny = -dy / L * th, dx / L * th
    line = (f"m {x + nx:.0f} {y + ny:.0f} l {tx + nx:.0f} {ty + ny:.0f} l {tx - nx:.0f} {ty - ny:.0f} l {x - nx:.0f} {y - ny:.0f}")
    r = base * 0.035
    ring = "m {:.0f} 0 ".format(r) + " ".join(
        f"l {r * math.cos(2 * math.pi * k / 28):.1f} {r * math.sin(2 * math.pi * k / 28):.1f}" for k in range(1, 29))
    t0, t1 = ass_time(start), ass_time(end)
    return [
        f"Dialogue: 0,{t0},{t1},Callout,,0,0,0,,{{\\an7\\pos(0,0)\\p1\\bord0\\shad0\\1c{col}\\clip({min(x, tx) - 1:.0f},0,{min(x, tx) + 1:.0f},{base * 4})"
        f"\\t(0,300,\\clip({min(x, tx) - 1:.0f},0,{max(x, tx) + 1:.0f},{base * 4}))\\fad(0,200)}}{line}{{\\p0}}",
        f"Dialogue: 0,{t0},{t1},Callout,,0,0,0,,{{\\an7\\pos({tx:.0f},{ty:.0f})\\org({tx:.0f},{ty:.0f})\\p1\\1a&HFF&\\3c{col}\\bord{th * 1.5:.1f}\\shad0"
        f"\\fscx20\\fscy20\\t(0,260,\\fscx120\\fscy120)\\t(260,420,\\fscx100\\fscy100)\\fad(0,200)}}{ring}{{\\p0}}",
    ]


def write_ass(edl: EDL, path: Path, burn_subs: bool = True) -> Path:
    W, H = edl.width, edl.height
    base = min(W, H)
    ss, ts = edl.subtitle_style or {}, edl.title_style or {}
    font = ss.get("font") or ts.get("font") or default_font()
    bar = int((H - W / 2.35) / 2) if edl.letterbox else 0
    sub_size = int(base * float(ss.get("size", 0.05)))
    title_size = int(base * float(ts.get("size", 0.085)))
    margin_v = int(H * float(ss.get("margin_v", 0.07))) + bar
    margin_lr = 60
    if H > W:   # 9:16: keep captions above the platform UI (bottom ~15%) and clear of the right-side buttons
        margin_v = max(margin_v, int(H * float(ss.get("safe_bottom", 0.16))))
        margin_lr = max(margin_lr, int(W * 0.09))
    prim = ass_color(ss.get("primary", "#FFFFFF"))
    outl = ass_color(ss.get("outline", "#000000"))
    tprim = ass_color(ts.get("primary", "#FFFFFF"))
    accent = ass_color(ts.get("accent", "#3DD6F5"))
    box = ass_color("#000000", 0x60)
    ow = float(ss.get("outline_w", 2.5)) * base / 1080
    bold_s = -1 if ss.get("bold") else 0
    bold_t = -1 if ts.get("bold", True) else 0
    styles = [
        # Name, Font, Size, Primary, Secondary, Outline, Back, Bold, Italic, U, S, ScX, ScY, Sp, Ang, BorderStyle, Outline, Shadow, Align, ML, MR, MV, Enc
        f"Style: Sub,{font},{sub_size},{prim},{prim},{outl},&H80000000,{bold_s},0,0,0,100,100,0,0,1,{ow:.1f},{ow * 0.4:.1f},2,{margin_lr},{margin_lr},{margin_v},1",
        f"Style: Title,{font},{title_size},{tprim},{tprim},&H90000000,&H90000000,{bold_t},0,0,0,100,100,2,0,1,{3 * base / 1080:.1f},{2 * base / 1080:.1f},5,80,80,0,1",
        f"Style: Section,{font},{int(title_size * 0.62)},{tprim},{tprim},{accent},&H90000000,{bold_t},0,0,0,100,100,1,0,1,{2 * base / 1080:.1f},0,8,80,80,{int(H * 0.08) + bar},1",
        f"Style: Lower,{font},{int(sub_size * 0.95)},&H00FFFFFF,&H00FFFFFF,{box},{box},{bold_t},0,0,0,100,100,0,0,3,{12 * base / 1080:.1f},0,1,{int(W * 0.05)},60,{int(H * 0.2) + bar},1",
        f"Style: Caption,{font},{int(sub_size * 1.05)},&H00FFFFFF,&H00FFFFFF,{accent},{accent},{bold_t},0,0,0,100,100,0,0,3,{10 * base / 1080:.1f},0,2,60,60,{int(H * 0.24) + bar},1",
        f"Style: CTA,{font},{int(title_size * 0.7)},&H00FFFFFF,&H00FFFFFF,{accent},{accent},{bold_t},0,0,0,100,100,1,0,3,{14 * base / 1080:.1f},0,2,80,80,{int(H * 0.3) + bar},1",
    ]
    kind_style = {"title": "Title", "section": "Section", "lower_third": "Lower", "caption": "Caption", "cta": "CTA",
                  "callout": "Callout"}
    styles.append(f"Style: Callout,{font},{int(sub_size * 0.95)},&H00FFFFFF,&H00FFFFFF,{accent},{accent},{bold_t},0,0,0,100,100,0,0,3,"
                  f"{10 * base / 1080:.1f},0,5,20,20,20,1")
    anchors = {  # kind → (\an, x, y)
        "title": (5, W / 2, H / 2), "section": (8, W / 2, H * 0.08 + bar), "lower_third": (1, W * 0.05, H * 0.8 - bar),
        "caption": (2, W / 2, H * 0.76 - bar), "cta": (2, W / 2, H * 0.7 - bar), "callout": (5, W / 2, H * 0.3),
    }
    defaults = {"title": "fade", "section": "fade", "lower_third": "fade", "caption": "fade", "cta": "fade", "callout": "pop"}
    defaults.update({k: v for k, v in (edl.text_anims or {}).items() if v})
    events = []
    for o in edl.overlays:
        st = kind_style.get(o.kind, "Caption")
        an, x, y = anchors.get(o.kind, anchors["caption"])
        if o.x is not None:
            x = o.x * W
        if o.y is not None:
            y = o.y * H
        anim = o.anim or defaults.get(o.kind, "fade")
        events += ass_anim_events(o.text, anim, st, an, x, y, o.start, o.end, W, H, accent_hex=ts.get("accent", "#3DD6F5"))
        if o.kind == "callout" and o.target:
            events += ass_callout_marker(x, y, o.target[0] * W, o.target[1] * H, o.start, o.end, base, ts.get("accent", "#3DD6F5"))
    sub_anim = (edl.text_anims or {}).get("subtitle", "")
    if burn_subs:
        for c in edl.subtitles:
            pre = ""
            if sub_anim == "pop":
                pre = "{\\fscx85\\fscy85\\t(0,120,\\fscx100\\fscy100)}"
            elif sub_anim == "kinetic":
                events += ass_anim_events(c.text, "kinetic", "Sub", 2, W / 2, H - margin_v, c.start, c.end, W, H, layer=0)
                continue
            events.append(f"Dialogue: 0,{ass_time(c.start)},{ass_time(c.end)},Sub,,0,0,0,,{pre}{ass_escape(c.text)}")
    content = "\n".join([
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {W}", f"PlayResY: {H}", "WrapStyle: 0",
        "ScaledBorderAndShadow: yes", "YCbCr Matrix: TV.709", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
        "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        *styles, "", "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text", *events, "",
    ])
    path.write_text(content, encoding="utf-8-sig")
    return path


def atempo_chain(speed: float) -> list[str]:
    out, s = [], speed
    while s > 2.0:
        out.append("atempo=2.0")
        s /= 2.0
    while s < 0.5:
        out.append("atempo=0.5")
        s /= 0.5
    out.append(f"atempo={s:.5f}")
    return out


def reframe_filter(mode: str, src_w: int, src_h: int, W: int, H: int, focus_x: float) -> str:
    if not src_w or not src_h:
        return f"scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2"
    sa, ta = src_w / src_h, W / H
    if abs(sa - ta) / ta < 0.03:
        return f"scale={W}:{H}"
    if mode == "auto":
        mode = "blur_pad" if sa < ta and ta >= 1 else "crop"
    fx = min(1.0, max(0.0, focus_x))
    if mode == "crop":
        return f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H}:(iw-{W})*{fx:.3f}:(ih-{H})/2"
    if mode == "pad":
        return f"scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:black"
    # blur_pad
    return (f"split=2[rbg][rfg];[rbg]scale={W // 4}:{H // 4}:force_original_aspect_ratio=increase,crop={W // 4}:{H // 4},"
            f"gblur=sigma=12,eq=brightness=-0.08,scale={W}:{H}[rbgb];[rfg]scale={W}:{H}:force_original_aspect_ratio=decrease[rfgs];"
            f"[rbgb][rfgs]overlay=(W-w)/2:(H-h)/2")


def _audio_chain_for(c: Clip, inp: str, dur_out: float) -> str:
    """Audio filter for an engine clip, ending in [a]. Ramped clips are muted (variable-speed audio sounds bad);
    a freeze inserts silence; otherwise atempo follows the constant speed."""
    fmt = "aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo"
    vol = f"volume={c.volume:.3f}"
    if c.ramp is not None:
        return f"{inp}volume=0,{fmt},apad,atrim=0:{dur_out:.3f}[a]"
    tempo = [] if abs(c.speed - 1) < 1e-3 else atempo_chain(c.speed)
    if "speed_ramp" in c.effects and not c.freeze:
        sp = c.src_duration * RAMP_SPLIT
        return (f"{inp}asplit=2[q1][q2];[q1]atrim=0:{sp:.3f},asetpts=PTS-STARTPTS,{','.join(atempo_chain(c.speed))}[qa];"
                f"[q2]atrim={sp:.3f},asetpts=PTS-STARTPTS,{','.join(atempo_chain(c.speed * RAMP_FACTOR))}[qb];"
                f"[qa][qb]concat=n=2:v=0:a=1,{vol},{fmt},afade=t=in:d=0.02,apad[a]")
    if c.freeze:
        at_src = c.freeze.at * c.speed
        tch = ("," + ",".join(tempo)) if tempo else ""
        return (f"{inp}asplit=2[f1][f2];[f1]atrim=0:{at_src:.3f},asetpts=PTS-STARTPTS{tch},{fmt}[fa];"
                f"[f2]atrim={at_src:.3f},asetpts=PTS-STARTPTS{tch},{fmt}[fb];"
                f"anullsrc=r=48000:cl=stereo,atrim=0:{c.freeze.hold:.3f},{fmt}[fz];"
                f"[fa][fz][fb]concat=n=3:v=0:a=1,{vol},afade=t=in:d=0.02,apad[a]")
    chain = ",".join(["asetpts=PTS-STARTPTS", *tempo, vol, fmt, "afade=t=in:d=0.02", "apad"])
    return f"{inp}{chain}[a]"


def _pan_filter(pan: float) -> str:
    """Equal-power pan for an sfx item (empty when centred)."""
    import math
    if abs(pan) < 0.02:
        return ""
    p = max(-1.0, min(1.0, pan))
    return f",pan=stereo|c0={math.cos((p + 1) * math.pi / 4) * math.sqrt(2):.4f}*c0|c1={math.sin((p + 1) * math.pi / 4) * math.sqrt(2):.4f}*c1"


# ----------------------------------------------------------------- pass 1


def _clip_job(project: Project, edl: EDL, c: Clip, cache_dir: Path, W: int, H: int, fps: int, quick: bool,
              encoder: str, hwaccel: str, lut_name: str, clip_start: float = 0.0, use_fx: bool = True) -> Path:
    if c.generated:   # terminal_hud insert card: no source file, rendered by the frame engine
        from .fx import ENGINE_VERSION
        beats = [round(b - clip_start, 3) for b in edl.beats if clip_start - 0.05 <= b <= clip_start + c.duration]
        key = short_hash(ENGINE_VERSION, c.model_dump_json(exclude={"note", "section", "role", "id", "transition_in"}),
                         [f.model_dump_json() for f in edl.look], beats, W, H, fps, edl.color_filter, lut_name, quick, encoder, n=16)
        out = cache_dir / f"gen_{key}.mp4"
        if out.exists() and out.stat().st_size > 0:
            return out
        from .fx.terminal import render_terminal
        part = out.with_name(f"{out.stem}.{uuid.uuid4().hex[:8]}.part.mp4")
        render_terminal(project, edl, c, clip_start, part, W, H, fps, quick=quick, encoder=encoder, lut_name=lut_name,
                        color_filter=edl.color_filter, cwd=cache_dir.parent)
        part.replace(out)
        return out
    src = Path(c.src)
    src = src if src.is_absolute() else project.root / src
    if not src.exists():
        raise FileNotFoundError(f"素材不存在：{src}")
    st = src.stat()
    engine = use_fx and (c.uses_engine() or bool(edl.look))
    extra: tuple = ()
    if engine:
        from .fx import ENGINE_VERSION
        beats = [round(b - clip_start, 3) for b in edl.beats if clip_start - 0.05 <= b <= clip_start + c.duration]
        pip_sig = ""
        if c.pip:
            p2 = Path(c.pip.src)
            p2 = p2 if p2.is_absolute() else project.root / p2
            pip_sig = f"{p2}:{p2.stat().st_size if p2.exists() else 0}"
        extra = (ENGINE_VERSION, c.model_dump_json(exclude={"note", "section", "role", "id", "transition_in"}),
                 [f.model_dump_json() for f in edl.look], beats, edl.downbeats and [round(b - clip_start, 3) for b in edl.downbeats
                                                                                  if clip_start - 0.05 <= b <= clip_start + c.duration],
                 pip_sig, (config.settings().get("render") or {}).get("equirect_width", 5760))
    key = short_hash(str(src.resolve()), st.st_size, int(st.st_mtime), c.in_, c.out, c.speed, sorted(c.effects),
                     W, H, fps, edl.reframe, c.focus_x, edl.color_filter, lut_name, c.volume, quick, encoder, *extra, n=16)
    out = cache_dir / f"{key}.mp4"
    if out.exists() and out.stat().st_size > 0:
        return out
    if engine:
        from .fx.engine import render_clip
        part = out.with_name(f"{key}.{uuid.uuid4().hex[:8]}.part.mp4")
        render_clip(project, edl, c, clip_start, part, W, H, fps, quick=quick, encoder=encoder, lut_name=lut_name,
                    color_filter=edl.color_filter, cwd=cache_dir.parent)
        part.replace(out)
        return out
    pi = probe(src)
    is_img = kind_of(src) == "image"
    dur_out = c.duration
    src_dur = c.src_duration
    vf: list[str] = []
    if "speed_ramp" in c.effects:
        sp = src_dur * 0.6
        s1, s2 = c.speed, c.speed * 2.5
        vf.append(f"split=2[r1][r2];[r1]trim=0:{sp:.3f},setpts=(PTS-STARTPTS)/{s1}[ra];"
                  f"[r2]trim={sp:.3f},setpts=(PTS-STARTPTS)/{s2}[rb];[ra][rb]concat=n=2:v=1:a=0")
    elif abs(c.speed - 1.0) > 1e-3:
        vf.append(f"setpts=(PTS-STARTPTS)/{c.speed}")
    else:
        vf.append("setpts=PTS-STARTPTS")
    vf.append(f"fps={fps}")
    dw, dh = pi.display_size if not is_img else (pi.width, pi.height)
    vf.append(reframe_filter(edl.reframe, dw, dh, W, H, c.focus_x))
    nframes = max(1, int(round(dur_out * fps)))
    if "zoom_in" in c.effects or "zoom_out" in c.effects:
        z = f"1+0.10*on/{nframes}" if "zoom_in" in c.effects else f"1.10-0.10*on/{nframes}"
        vf.append(f"zoompan=z='{z}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s={W}x{H}:fps={fps}")
    if edl.color_filter:
        vf.append(edl.color_filter)
    if lut_name:
        vf.append(f"lut3d=file={lut_name}")
    if "bw" in c.effects:
        vf.append("hue=s=0")
    if "vignette" in c.effects:
        vf.append("vignette=PI/5")
    vf.append("setsar=1,format=yuv420p")
    vchain = ",".join(vf)

    args: list[str] = []
    if is_img:
        args += ["-loop", "1", "-t", f"{dur_out:.3f}", "-i", str(src)]
    else:
        args += [*(["-hwaccel", hwaccel] if hwaccel not in ("", "none") else []),
                 "-ss", f"{c.in_:.3f}", "-t", f"{src_dur:.3f}", "-i", str(src)]
    has_audio = pi.has_audio and not is_img and c.volume > 0.001
    if has_audio:
        if "speed_ramp" in c.effects:
            sp = src_dur * 0.6
            ach = (f"asplit=2[q1][q2];[q1]atrim=0:{sp:.3f},asetpts=PTS-STARTPTS,{','.join(atempo_chain(c.speed))}[qa];"
                   f"[q2]atrim={sp:.3f},asetpts=PTS-STARTPTS,{','.join(atempo_chain(c.speed * 2.5))}[qb];[qa][qb]concat=n=2:v=0:a=1")
        else:
            ach = ",".join(["asetpts=PTS-STARTPTS", *([] if abs(c.speed - 1) < 1e-3 else atempo_chain(c.speed))])
        ach += (f",volume={c.volume:.3f},aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,"
                f"afade=t=in:d=0.02,apad")
        fc = f"[0:v]{vchain}[v];[0:a]{ach}[a]"
    else:
        args += ["-f", "lavfi", "-t", f"{dur_out:.3f}", "-i", "anullsrc=r=48000:cl=stereo"]
        fc = f"[0:v]{vchain}[v];[1:a]aformat=sample_fmts=fltp:channel_layouts=stereo[a]"
    part = out.with_name(f"{key}.{uuid.uuid4().hex[:8]}.part.mp4")
    venc = (video_encode_args(encoder, {"crf": 16, "nvenc_cq": 17}, fast=True) if not quick
            else video_encode_args("libx264" if "nvenc" not in encoder else encoder, {"crf": 23}, fast=True))
    cmd = [*args, "-filter_complex", fc, "-map", "[v]", "-map", "[a]", "-t", f"{dur_out:.3f}",
           *venc, "-g", str(fps), "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-r", str(fps),
           "-video_track_timescale", str(fps * 1000), str(part)]
    cwd = cache_dir.parent
    try:
        ffmpeg(cmd, cwd=cwd)
    except FFmpegError:
        if hwaccel not in ("", "none") and not is_img:  # retry without hw decode
            cmd = [a for a in cmd]
            i = cmd.index("-hwaccel")
            del cmd[i:i + 2]
            ffmpeg(cmd, cwd=cwd)
        else:
            raise
    part.replace(out)  # atomic; identical clips rendered twice just overwrite each other
    return out


# ----------------------------------------------------------------- pass 2


def _enable_expr(ranges: list[tuple[float, float]]) -> str:
    return "+".join(f"between(t,{a:.2f},{b:.2f})" for a, b in ranges) or "0"


def _flash_expr(flashes: list[list[float]]) -> str:
    terms = [f"{min(1.0, max(0.0, st)):.2f}*exp(-(t-{t0:.3f})*16)*gte(t,{t0:.3f})*lt(t,{t0 + 0.45:.3f})"
             for t0, st in ((f[0], f[1] if len(f) > 1 else 0.7) for f in flashes)]
    return "min(0.6,0.6*(" + "+".join(terms) + "))" if terms else "0"


def _hex(c: str, default: str = "3DD6F5") -> str:
    h = (c or default).lstrip("#")
    return h if len(h) == 6 else default


def render(project: Project, edl: EDL | None = None, *, out: Path | None = None, quick: bool = False,
           encoder_pref: str | None = None, subtitles_mode: str | None = None, workers: int | None = None,
           use_fx: bool = True) -> Path:
    edl = edl or EDL.load(project.edl_path)
    if not (config.settings().get("render") or {}).get("fx", True):
        use_fx = False
    if not edl.clips:
        raise ValueError("EDL 里没有片段")
    rcfg = config.settings().get("render") or {}
    acfg = config.settings().get("analysis") or {}
    W, H, fps = edl.width, edl.height, edl.fps
    if quick:
        W, H = (W // 2) // 2 * 2, (H // 2) // 2 * 2
        edl = edl.model_copy(deep=True)
        edl.width, edl.height = W, H
    if not use_fx:
        edl = edl.model_copy(deep=True)
        edl.look, edl.flashes, edl.progress = [], [], None
        for c in edl.clips:
            if c.transition_in.is_custom:
                c.transition_in.type = "fade"
    encoder = pick_encoder(encoder_pref or rcfg.get("encoder", "auto"))
    hwaccel = str(acfg.get("hwaccel", "auto"))
    subs_mode = subtitles_mode or rcfg.get("subtitles", "burn")
    work = (project.renders_dir / "_work").resolve()
    cache_dir = work / "clips"
    cache_dir.mkdir(parents=True, exist_ok=True)
    lut_name = ""
    if edl.lut:
        lp = Path(edl.lut)
        lp = lp if lp.is_absolute() else project.root / lp
        if lp.exists():
            lut_name = f"lut_{short_hash(lp.resolve())}{lp.suffix}"
            shutil.copy2(lp, work / lut_name)
        else:
            warn(f"LUT 不存在，忽略：{edl.lut}")
    edl.normalize_transitions()
    tl = edl.timeline()
    n_eng = sum(1 for c in edl.clips if use_fx and (c.uses_engine() or edl.look))
    info(f"渲染 {len(edl.clips)} 个片段 → {W}x{H}@{fps}（编码器 {encoder}{'，快速预览' if quick else ''}"
         f"{f'，{n_eng} 个片段走特效引擎' if n_eng else ''}）")

    # ---- pass 1 (parallel, cached)
    n_workers = workers or max(1, min(4, (os.cpu_count() or 2) // 2))
    with ThreadPoolExecutor(max_workers=n_workers) as ex:
        futs = [ex.submit(_clip_job, project, edl, c, cache_dir, W, H, fps, quick, encoder, hwaccel, lut_name, tl[i][0], use_fx)
                for i, c in enumerate(edl.clips)]
        mezz = [f.result() for f in futs]

    # ---- pass 1.5: custom (frame-level) transitions between mezzanines
    trans: dict[int, Path] = {}
    jobs = []
    for i in range(1, len(edl.clips)):
        tr = edl.clips[i].transition_in
        if tr.is_custom and tr.duration > 0:
            key = short_hash("tr", ENGINE_TR_VERSION, tr.type, round(tr.duration, 3), str(mezz[i - 1]), str(mezz[i]), n=16)
            outp = cache_dir / f"tr_{key}.mp4"
            trans[i] = outp
            if not (outp.exists() and outp.stat().st_size > 0):
                jobs.append((i, outp))
    if jobs:
        from .fx.transitions import render_transition

        def _tr(job):
            i, outp = job
            part = outp.with_name(f"{outp.stem}.{uuid.uuid4().hex[:8]}.part.mp4")
            render_transition(edl.clips[i].transition_in.type, mezz[i - 1], edl.clips[i - 1].duration, mezz[i],
                              edl.clips[i].transition_in.duration, part, W, H, fps, encoder=encoder, quick=quick, seed=i)
            part.replace(outp)

        with ThreadPoolExecutor(max_workers=n_workers) as ex:
            list(ex.map(_tr, jobs))

    # ---- pass 2
    total = edl.total_duration
    inputs: list[str] = []
    for m in mezz:
        inputs += ["-i", str(Path(m).resolve())]
    n = len(mezz)
    tr_input: dict[int, int] = {}
    for i, pth in trans.items():
        tr_input[i] = len(inputs) // 2
        inputs += ["-i", str(pth.resolve())]
    fc: list[str] = []
    for i, c in enumerate(edl.clips):
        nf = int(round(c.duration * fps))
        f0 = int(round(edl.clips[i].transition_in.duration * fps)) if i in trans else 0
        f1 = nf - (int(round(edl.clips[i + 1].transition_in.duration * fps)) if (i + 1) in trans else 0)
        fc.append(f"[{i}:v]settb=AVTB,setpts=PTS-STARTPTS,fps={fps},trim=start_frame={f0}:end_frame={max(f0 + 1, f1)},"
                  f"setpts=PTS-STARTPTS,fps={fps},setsar=1[v{i}]")
        fc.append(f"[{i}:a]asetpts=PTS-STARTPTS[a{i}]")
    for i, k in tr_input.items():
        nf = int(round(edl.clips[i].transition_in.duration * fps))
        fc.append(f"[{k}:v]settb=AVTB,setpts=PTS-STARTPTS,fps={fps},trim=end_frame={nf},setpts=PTS-STARTPTS,fps={fps},setsar=1[t{i}]")

    def frames_of(i: int) -> int:
        nf = int(round(edl.clips[i].duration * fps))
        f0 = int(round(edl.clips[i].transition_in.duration * fps)) if i in trans else 0
        f1 = nf - (int(round(edl.clips[i + 1].transition_in.duration * fps)) if (i + 1) in trans else 0)
        return max(f0 + 1, f1) - f0

    acc_v, acc_a, acc_f = "v0", "a0", frames_of(0)
    acc_ad = edl.clips[0].duration
    transition_fallbacks = set()
    for i in range(1, n):
        c = edl.clips[i]
        t = XFADE.get(c.transition_in.type)
        nv, na = f"vx{i}", f"ax{i}"
        d = c.transition_in.duration
        if i in trans:
            fc.append(f"[{acc_v}][t{i}][v{i}]concat=n=3:v=1:a=0,settb=AVTB,fps={fps}[{nv}]")
            acc_f += int(round(d * fps)) + frames_of(i)
        elif t is None or d <= 0:
            fc.append(f"[{acc_v}][v{i}]concat=n=2:v=1:a=0,settb=AVTB,fps={fps}[{nv}]")
            acc_f += frames_of(i)
        else:
            supported = compatible_xfade(t)
            if supported != t and t not in transition_fallbacks:
                note = f"当前 FFmpeg 不支持 {t} 转场，改用 {supported}，保留转场时长。"
                warn(note)
                transition_fallbacks.add(t)
            t = supported
            fc.append(f"[{acc_v}][v{i}]xfade=transition={t}:duration={d:.3f}:offset={acc_f / fps - d:.3f}[{nv}]")
            acc_f += frames_of(i) - int(round(d * fps))
        if d > 0 and (i in trans or t is not None):
            fc.append(f"[{acc_a}][a{i}]acrossfade=d={d:.3f}:c1=tri:c2=tri[{na}]")
            acc_ad += c.duration - d
        else:
            fc.append(f"[{acc_a}][a{i}]concat=n=2:v=0:a=1[{na}]")
            acc_ad += c.duration
        acc_v, acc_a = nv, na

    vlast = acc_v
    if edl.flashes:
        fc.append(f"[{vlast}]eq=eval=frame:brightness='{_flash_expr(edl.flashes)}':"
                  f"saturation='1-0.8*({_flash_expr(edl.flashes)})'[vfl]")
        vlast = "vfl"
    if edl.letterbox:
        bar = int((H - W / 2.35) / 2)
        fc.append(f"[{vlast}]drawbox=x=0:y=0:w=iw:h={bar}:color=black:t=fill,"
                  f"drawbox=x=0:y=ih-{bar}:w=iw:h={bar}:color=black:t=fill[vlb]")
        vlast = "vlb"
    next_in = len(inputs) // 2
    if edl.logo and Path(edl.logo.src).exists():
        inputs += ["-loop", "1", "-t", f"{total:.3f}", "-i", edl.logo.src]
        lw = int(W * edl.logo.scale)
        m = int(min(W, H) * 0.04)
        pos = {"top_right": (f"W-w-{m}", f"{m}"), "top_left": (f"{m}", f"{m}"),
               "bottom_right": (f"W-w-{m}", f"H-h-{m}"), "bottom_left": (f"{m}", f"H-h-{m}")}[edl.logo.position]
        end = edl.logo.end if edl.logo.end is not None else total
        fc.append(f"[{next_in}:v]scale={lw}:-1,format=rgba,colorchannelmixer=aa={edl.logo.opacity}[logo]")
        fc.append(f"[{vlast}][logo]overlay={pos[0]}:{pos[1]}:enable='between(t,{edl.logo.start:.2f},{end:.2f})':eof_action=pass[vlg]")
        vlast = "vlg"
        next_in += 1
    if edl.progress:
        pb = edl.progress
        hv = float(pb.get("height", 0.008))
        hpx = hv * min(W, H) / 1080 if hv >= 1 else hv * min(W, H)  # ≥1: pixels at 1080p, <1: fraction
        ph = max(4, int(hpx) // 2 * 2)
        top = pb.get("position", "bottom") == "top"
        bar_y = 0 if top else H - ph
        if edl.letterbox:
            barh = int((H - W / 2.35) / 2)
            bar_y = barh if top else H - barh - ph
        col = _hex(pb.get("color", ""))
        fc.append(f"color=c=0x{col}:s={W}x{ph}:r={fps}:d={total:.3f}[pbc]")
        chain = f"[{vlast}]drawbox=x=0:y={bar_y}:w=iw:h={ph}:color=black@0.35:t=fill[pbb]"
        fc.append(chain)
        fc.append(f"[pbb][pbc]overlay=x='-W+W*t/{total:.3f}':y={bar_y}:eof_action=pass[pbo]")
        vlast = "pbo"
        ticks = [float(c[0]) for c in (pb.get("chapters") or []) if 0.5 < float(c[0]) < total - 0.5]
        if ticks:
            tw = max(2, W // 480)
            fc.append(f"[{vlast}]" + ",".join(f"drawbox=x={int(W * t0 / total) - tw // 2}:y={bar_y}:w={tw}:h={ph}:color=black@0.8:t=fill"
                                             for t0 in ticks) + "[pbt]")
            vlast = "pbt"
    burn = subs_mode in ("burn", "both")
    ass_path = write_ass(edl, work / "text.ass", burn_subs=burn)
    if edl.overlays or (burn and edl.subtitles):
        fc.append(f"[{vlast}]ass={ass_path.name}[vtxt]")
        vlast = "vtxt"
    fc.append(f"[{vlast}]format=yuv420p[vout]")

    # audio: camera bus + voiceover -> speech bus ; music ducked by speech
    speech_ranges: list[tuple[float, float]] = []
    for c, (s, e) in zip(edl.clips, edl.timeline()):
        if c.role in ("talking_head", "interview") and c.volume >= 0.5:
            speech_ranges.append((s, e))
    bus = [acc_a]
    for k, a in enumerate(edl.audio):
        if a.kind == "voiceover":
            src = a.src.split("#")[0]
            inputs += ["-i", src]
            ms = int(a.start * 1000)
            fc.append(f"[{next_in}:a]atrim=start={a.in_:.3f}:duration={a.duration:.3f},asetpts=PTS-STARTPTS,"
                      f"aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,volume={a.volume},"
                      f"afade=t=in:d={a.fade_in:.2f},afade=t=out:st={max(0, a.duration - a.fade_out):.2f}:d={a.fade_out:.2f},"
                      f"adelay={ms}|{ms}[vo{k}]")
            bus.append(f"vo{k}")
            speech_ranges.append((a.start, a.start + a.duration))
            next_in += 1
    if len(bus) > 1:
        fc.append("".join(f"[{b}]" for b in bus) + f"amix=inputs={len(bus)}:normalize=0:duration=first[speech]")
    else:
        fc.append(f"[{acc_a}]anull[speech]")
    music = [a for a in edl.audio if a.kind == "music"]
    if music:
        mixins = []
        for k, a in enumerate(music):
            if a.loop:
                inputs += ["-stream_loop", "-1"]
            inputs += ["-i", a.src]
            ms = int(a.start * 1000)
            fo_st = max(0.0, a.duration - a.fade_out)
            fc.append(f"[{next_in}:a]atrim=start={a.in_:.3f}:duration={a.duration:.3f},asetpts=PTS-STARTPTS,"
                      f"aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,volume={a.volume},"
                      f"afade=t=in:d={a.fade_in:.2f},afade=t=out:st={fo_st:.2f}:d={a.fade_out:.2f},adelay={ms}|{ms}[mu{k}]")
            mixins.append(f"mu{k}")
            next_in += 1
        if len(mixins) > 1:
            fc.append("".join(f"[{m}]" for m in mixins) + f"amix=inputs={len(mixins)}:normalize=0[music]")
        else:
            fc.append(f"[{mixins[0]}]anull[music]")
        if any(a.duck for a in music) and speech_ranges:
            fc.append("[speech]asplit=2[sp_main][sp_key0]")
            fc.append(f"[sp_key0]volume=0:enable='not({_enable_expr(speech_ranges)})'[sp_key]")
            fc.append("[music][sp_key]sidechaincompress=threshold=0.02:ratio=8:attack=20:release=400:makeup=1[music_d]")
            fc.append("[sp_main][music_d]amix=inputs=2:normalize=0:duration=first[mix]")
        else:
            fc.append("[speech][music]amix=inputs=2:normalize=0:duration=first[mix]")
    else:
        fc.append("[speech]anull[mix]")
    sfx = [a for a in edl.audio if a.kind == "sfx" and Path(a.src).exists()] if use_fx else []
    if sfx:
        labels = []
        for k, a in enumerate(sfx):
            inputs += ["-i", a.src]
            ms = max(0, int(a.start * 1000))
            dur = f":duration={a.duration:.3f}" if a.duration > 0 else ""
            fc.append(f"[{next_in}:a]atrim=start={a.in_:.3f}{dur},asetpts=PTS-STARTPTS,aresample=48000,"
                      f"aformat=sample_fmts=fltp:channel_layouts=stereo,volume={a.volume:.3f}{_pan_filter(a.pan)},adelay={ms}|{ms}[sx{k}]")
            labels.append(f"sx{k}")
            next_in += 1
        fc.append("".join(f"[{x}]" for x in labels) + f"amix=inputs={len(labels)}:normalize=0[sfxbus]")
        fc.append("[mix][sfxbus]amix=inputs=2:normalize=0:duration=first[mix2]")
        mixl = "mix2"
    else:
        mixl = "mix"
    lufs = float(rcfg.get("loudness_lufs", -14))
    fc.append(f"[{mixl}]loudnorm=I={lufs}:TP=-1.5:LRA=11,aresample=48000,atrim=end={total:.3f}[aout]")

    script = work / "graph.txt"
    script.write_text(";\n".join(fc), encoding="utf-8")
    project.renders_dir.mkdir(parents=True, exist_ok=True)
    if out is None:
        stem = f"{edl.project or project.root.name}_{edl.style}_{edl.aspect.replace(':', 'x')}{'_quick' if quick else ''}"
        k = 1
        while (project.renders_dir / f"{stem}_v{k}.mp4").exists():
            k += 1
        out = project.renders_dir / f"{stem}_v{k}.mp4"
    out = Path(out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp_out = out.with_name(out.stem + ".rendering.mp4")
    venc = video_encode_args(encoder, rcfg, fast=quick)
    cmd = [*inputs, *file_option("filter_complex", script.name), "-map", "[vout]", "-map", "[aout]", *venc,
           "-r", str(fps), "-c:a", "aac", "-b:a", str(rcfg.get("audio_bitrate", "192k")),
           "-movflags", "+faststart", "-t", f"{total:.3f}", str(tmp_out)]
    try:
        ffmpeg(cmd, cwd=work)
    except Exception:
        tmp_out.unlink(missing_ok=True)
        raise
    try:
        _fix_loudness(tmp_out, lufs, rcfg, work)
    except Exception as e:  # never lose a finished render over a loudness touch-up
        warn(f"响度二次校正跳过：{e}")
    tmp_out.replace(out)
    if subs_mode in ("sidecar", "both", "burn") and edl.subtitles:
        write_srt(edl, out.with_suffix(".srt"))
    ok(f"渲染完成：{out}（{total:.1f}s）")
    return out
