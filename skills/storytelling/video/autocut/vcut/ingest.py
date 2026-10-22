"""vcut ingest: bring footage into a project, probe metadata, detect device."""
from __future__ import annotations

import os
import shutil
from pathlib import Path

from . import config
from .devices import detect_device
from .media import SKIP_NAMES, is_equirect_size, kind_of, probe
from .project import Project
import re

from rich.markup import escape

from .util import info, ok, short_hash, warn

MUSIC_HINT = re.compile(r"music|bgm|配乐|音乐|曲库", re.I)

INSV_HELP = (
    "检测到 Insta360 360° 原始文件（.insv）。三种用法（推荐顺序）：\n"
    "  A) 推荐：Insta360 Studio 导入 .insv → 导出「全景 2:1 MP4」（开启 FlowState 防抖 + 水平校正，H.265，5.7K/30fps），\n"
    "     再 `autocut ingest` 导入：本工具会识别为 360° 素材，自动运镜（跟随/环绕/小行星/甩镜/隐形自拍杆）。\n"
    "  B) Studio 里直接重构图(Reframe)导出 16:9 / 9:16 平面 MP4，再导入（按普通素材剪）。\n"
    "  C) 没装 Studio 时的应急：`autocut x5-stitch <文件.insv>` 用 ffmpeg v360 双鱼眼粗拼成 2:1 全景\n"
    "     （无防抖、无陀螺仪水平校正、无拼接缝融合，接缝处可能有错位，仅适合预览/应急）。\n"
    "  .lrv 是相机生成的低清代理文件，不需要导入。"
)


def _iter_files(paths: list[Path]):
    for p in paths:
        p = Path(p).expanduser()
        if p.is_dir():
            for f in sorted(p.rglob("*")):
                if f.is_file() and f.name.lower() not in SKIP_NAMES and not f.name.startswith("."):
                    yield f
        elif p.is_file():
            yield p
        else:
            warn(f"路径不存在：{p}")


def _place(src: Path, dst: Path, mode: str) -> str:
    """Return the mode actually used."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    if mode == "link":
        try:
            os.link(src, dst)
            return "hardlink"
        except OSError:
            try:
                os.symlink(src, dst)
                return "symlink"
            except OSError:
                pass  # Windows without developer mode / cross-drive -> copy
        shutil.copy2(src, dst)
        return "copy"
    shutil.copy2(src, dst)
    return "copy"


def ingest(project: Project, paths: list[Path], mode: str = "copy", as_kind: str = "auto",
           include_raw360: bool = False) -> dict:
    items = project.media()
    known = {(m.get("source_name"), m.get("size")) for m in items}
    added, skipped, raw360, proxies = [], [], [], []
    for f in _iter_files(paths):
        kind = kind_of(f)
        size = f.stat().st_size
        if kind == "raw360":
            raw360.append(f)
            if not include_raw360:
                continue
        if kind == "proxy":
            proxies.append(f)
            continue
        if kind == "other":
            skipped.append(f)
            continue
        if (f.name, size) in known:
            skipped.append(f)
            continue
        # target folder
        eff_as = as_kind
        if kind == "audio" and as_kind == "auto":
            eff_as = "music" if MUSIC_HINT.search(f.as_posix()) else "voiceover"
        if kind == "audio":
            sub = {"music": "audio/music", "voiceover": "audio/voiceover"}.get(eff_as, "audio/voiceover")
        elif kind == "image":
            sub = "assets"
        elif kind == "raw360":
            sub = "footage/_raw360"
        else:
            sub = "footage"
        pi = probe(f)
        dev = detect_device(f, pi)
        projection = "flat"
        if kind == "video" and is_equirect_size(*pi.display_size):
            projection = "equirect"
            if dev.get("kind") != "360":
                d360 = next((d for d in config.devices() if str(d.get("kind")) == "360"), None)
                if d360:
                    dev = {"id": d360["id"], "label": d360.get("label", d360["id"]), "kind": "360", "score": 3,
                           "reasons": ["2:1 全景画幅"], "confidence": "medium"}
        if kind == "video" and sub == "footage":
            sub = f"footage/{dev['id']}"
        mid = short_hash(f.name, size, int(f.stat().st_mtime))
        if mode == "ref":
            rel = str(f.resolve())
            used = "ref"
        else:
            dst = project.root / sub / f.name
            if dst.exists():
                dst = dst.with_name(f"{dst.stem}_{mid}{dst.suffix}")
            used = _place(f, dst, mode)
            rel = dst.relative_to(project.root).as_posix()
        role = eff_as if eff_as != "auto" else kind
        item = {
            "id": mid,
            "path": rel,
            "source_name": f.name,
            "source_path": str(f.resolve()),
            "kind": kind,
            "role": role,
            "ingest_mode": used,
            "size": size,
            "device": dev,
            "probe": pi.to_dict(),
            "needs_export": kind == "raw360",
            "projection": projection,
        }
        items.append(item)
        known.add((f.name, size))
        added.append(item)
    project.save_media(items)

    for it in added:
        p = it["probe"]
        desc = f"{p.get('display_width')}x{p.get('display_height')} {p.get('fps') or ''}fps {p.get('duration', 0):.1f}s" \
            if it["kind"] == "video" else it["kind"]
        conf = it["device"]["confidence"]
        info(escape(f"  + [{it['id']}] {it['source_name']}  →  {it['device']['label']}（{conf}）  {desc}"
                    + ("  [360° 全景，可自动运镜]" if it.get("projection") == "equirect" else "")))
        if p.get("bit_depth") == 10 or (p.get("color_transfer") or "") in ("arib-std-b67", "smpte2084"):
            warn(f"{it['source_name']} 是 10bit/HDR/Log 素材，渲染会转为 8bit SDR，颜色可能偏灰，建议在相机/Studio 里导出 Rec.709。")
    if raw360:
        warn(f"{len(raw360)} 个 .insv 360° 原始文件" + ("（已按要求放入 footage/_raw360，不参与剪辑）" if include_raw360 else "未导入") + "：")
        for r in raw360[:10]:
            info(escape(f"    {r.name}"))
        info(INSV_HELP)
    if proxies:
        info(f"  跳过 {len(proxies)} 个 .lrv 低清代理文件（相机自动生成，不需要）。")
    if skipped:
        info(f"  跳过 {len(skipped)} 个已存在或不支持的文件。")
    ok(f"导入 {len(added)} 个文件，项目共 {len(items)} 个媒体。")
    return {"added": added, "raw360": [str(r) for r in raw360], "skipped": [str(s) for s in skipped]}
