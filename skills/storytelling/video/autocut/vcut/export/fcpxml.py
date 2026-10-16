"""FCPXML 1.9 export (opens in DaVinci Resolve / Final Cut Pro) — cheap interchange fallback."""
from __future__ import annotations

import xml.etree.ElementTree as ET
from fractions import Fraction
from pathlib import Path
from urllib.parse import quote

from ..edl import EDL
from ..media import probe
from ..project import Project
from ..util import ok
from .timemap import nle_layout, ramp_parts, remap


def _t(seconds: float, fps: int) -> str:
    frames = int(round(seconds * fps))
    f = Fraction(frames * 1000, fps * 1000)
    return f"{f.numerator}/{f.denominator}s" if f.denominator != 1 else f"{f.numerator}s"


def _uri(p: Path) -> str:
    s = p.resolve().as_posix()
    return "file://" + ("/" if not s.startswith("/") else "") + quote(s)


def export_fcpxml(project: Project, edl: EDL, out: Path | None = None) -> Path:
    fps = edl.fps
    out = out or project.drafts_dir / f"{edl.project or project.root.name}.fcpxml"
    root = ET.Element("fcpxml", version="1.9")
    res = ET.SubElement(root, "resources")
    fmt_id = "r0"
    ET.SubElement(res, "format", id=fmt_id, name=f"FFVideoFormat{edl.height}p{fps}", frameDuration=f"1/{fps}s",
                  width=str(edl.width), height=str(edl.height))
    assets: dict[str, str] = {}

    def asset(path: Path, has_video: bool = True) -> str:
        key = str(path.resolve())
        if key in assets:
            return assets[key]
        aid = f"a{len(assets) + 1}"
        pi = probe(path)
        a = ET.SubElement(res, "asset", id=aid, name=path.name, start="0s", duration=_t(max(pi.duration, 0.04), fps),
                          hasVideo="1" if has_video and pi.has_video else "0", hasAudio="1" if pi.has_audio else "0",
                          format=fmt_id, audioSources="1", audioChannels="2")
        ET.SubElement(a, "media-rep", kind="original-media", src=_uri(path))
        assets[key] = aid
        return aid

    lib = ET.SubElement(root, "library")
    ev = ET.SubElement(lib, "event", name="autocut")
    proj = ET.SubElement(ev, "project", name=edl.title or edl.project)
    layout = nle_layout(edl)
    total = layout[-1][1] if layout else 0
    seq = ET.SubElement(proj, "sequence", format=fmt_id, duration=_t(total, fps), tcStart="0s", tcFormat="NDF")
    spine = ET.SubElement(seq, "spine")
    first_clip = None
    for c, (s, _e) in zip(edl.clips, layout):
        src = Path(c.src)
        src = src if src.is_absolute() else project.root / src
        if c.generated:   # generated cards have no source file: use the pre-rendered mezzanine
            from .jianying import bake_clip
            src = bake_clip(project, edl, c, 0.0, project.drafts_dir / "fcpxml_media")
        aid = asset(src)
        t = s
        for a, b, sp in ramp_parts(c):
            d = (b - a) / sp
            el = ET.SubElement(spine, "asset-clip", ref=aid, name=src.name, offset=_t(t, fps), start=_t(a, fps),
                               duration=_t(d, fps), format=fmt_id, tcFormat="NDF")
            if abs(sp - 1) > 1e-3:
                tm = ET.SubElement(el, "timeMap")
                ET.SubElement(tm, "timept", time="0s", value=_t(a, fps), interp="linear")
                ET.SubElement(tm, "timept", time=_t(d, fps), value=_t(b, fps), interp="linear")
            if c.volume != 1.0:
                import math
                db = 20 * math.log10(max(c.volume, 1e-3))
                ET.SubElement(el, "adjust-volume", amount=f"{db:.1f}dB")
            first_clip = first_clip if first_clip is not None else el
            t += d
    # connected audio (music / voiceover) on lanes below the first clip
    if first_clip is not None:
        for lane, a in enumerate([a for a in edl.audio], start=1):
            p = Path(a.src.split("#")[0])
            if not p.exists():
                continue
            aid = asset(p, has_video=False)
            start = remap(edl, a.start)
            # connected-clip offsets live in the parent's local (source) time
            parent_start = edl.clips[0].in_
            ET.SubElement(first_clip, "asset-clip", ref=aid, lane=str(-lane), name=p.name, offset=_t(parent_start + start, fps),
                          start=_t(a.in_, fps), duration=_t(min(a.duration, total - start), fps))
    ET.indent(root)
    out.parent.mkdir(parents=True, exist_ok=True)
    xml = '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE fcpxml>\n' + ET.tostring(root, encoding="unicode")
    out.write_text(xml, encoding="utf-8")
    ok(f"FCPXML：{out}（DaVinci Resolve：文件→导入→时间线）")
    return out
