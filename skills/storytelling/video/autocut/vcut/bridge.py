"""与 storytelling toolkit 其余视频工具的桥接。

toolkit（video/run）已有：inspect（素材索引 manifest.json）、transcribe（本地 ASR transcript.json）、
render（edit.json v1 → master.mp4）、narrate（旁白装配 narration.wav + zh/en.srt）、mix（混音）。
autocut（本包）在它们之上增加：项目制素材管理、设备/镜头理解、拍摄清单与补拍提醒、带风格的 EDL 规划、
运镜/特效/360、剪映草稿。这里只做格式转换，不重复实现渲染、转写等 toolkit 已有的能力。

  export_edit      EDL  → toolkit edit.json v1（有损：转场/运镜/特效/变速曲线会丢，返回警告列表）
  import_edit      edit.json v1 → 项目 EDL（素材入库，字幕/配乐一并带入）
  import_index     toolkit inspect 的 manifest.json → 素材入库
  import_transcript toolkit transcribe 的 transcript.json → 供 analyze 复用，省掉重复转写
  import_narration toolkit narrate 的输出目录 → EDL 旁白轨 + 字幕
  toolkit_transcribe 把转写交给 toolkit 的 transcribe.py（asr.engine: toolkit）
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

from .edl import EDL, AudioItem, Clip, SubtitleCue
from .project import ASPECTS, Project
from .util import info, read_json, warn, write_json

_CJK = re.compile(r"[\u3400-\u9fff\u3040-\u30ff\uac00-\ud7af]")


def toolkit_video_dir() -> Path | None:
    """video/ 目录（含 run、scripts/）。env VCUT_TOOLKIT_VIDEO 优先；独立安装 vcut 时返回 None。"""
    cands = [os.environ.get("VCUT_TOOLKIT_VIDEO"), str(Path(__file__).resolve().parents[2])]
    for c in cands:
        if c and (Path(c) / "scripts" / "render.py").exists():
            return Path(c)
    return None


# ------------------------------------------------------------------ helpers
def _even(n: int) -> int:
    return max(2, int(n) // 2 * 2)


def _rel(path: str | Path, base: Path) -> str:
    try:
        return os.path.relpath(str(path), str(base)).replace("\\", "/")
    except ValueError:  # 不同盘符
        return str(path)


def _aspect_of(w: int, h: int) -> str:
    best, err = "16:9", 9.9
    for name, (aw, ah) in ASPECTS.items():
        e = abs(aw / ah - w / h)
        if e < err:
            best, err = name, e
    return best


def parse_srt(text: str) -> list[tuple[float, float, str]]:
    def sec(s: str) -> float:
        h, m, rest = s.strip().split(":")
        return int(h) * 3600 + int(m) * 60 + float(rest.replace(",", "."))
    out = []
    for block in re.split(r"\n\s*\n", text.strip().replace("\r\n", "\n")):
        lines = [x for x in block.split("\n") if x.strip()]
        for i, ln in enumerate(lines):
            if "-->" in ln:
                a, b = ln.split("-->")
                body = " ".join(lines[i + 1:]).strip()
                if body:
                    out.append((sec(a), sec(b), body))
                break
    return out


# ------------------------------------------------------------------ export
def export_edit(project: Project, edl: EDL, out: Path, fit: str = "cover") -> tuple[dict, list[str]]:
    """EDL → toolkit edit.json（version 1）。素材路径相对 edit.json 所在目录，跨盘符时用绝对路径。"""
    base = out.resolve().parent
    warnings: list[str] = []
    tl = edl.timeline()
    plan: dict = {"version": 1, "title": edl.title or edl.project or project.root.name,
                  "output": {"width": _even(edl.width), "height": _even(edl.height), "fps": int(edl.fps), "fit": fit},
                  "clips": [], "captions": []}
    lossy = {"transition": 0, "move": 0, "fx": 0, "speed": 0, "freeze": 0, "pip": 0, "360": 0}
    for c in edl.clips:
        src = Path(c.src)
        if not src.is_absolute():
            src = project.root / src
        item = {"source": _rel(src, base), "in": round(c.in_, 3), "out": round(c.out, 3),
                "reason": (f"{c.role}" + (f"：{c.note}" if c.note else "")).strip()}
        plan["clips"].append(item)
        if c.transition_in.type != "cut":
            lossy["transition"] += 1
        lossy["move"] += bool(c.move and c.move.type not in ("", "none"))
        lossy["fx"] += bool(c.fx or c.effects)
        lossy["speed"] += bool(c.ramp or c.speed != 1.0)
        lossy["freeze"] += bool(c.freeze)
        lossy["pip"] += bool(c.pip)
        lossy["360"] += c.projection == "equirect"
    names = {"transition": "转场", "move": "运镜", "fx": "特效", "speed": "变速", "freeze": "定格", "pip": "画中画/分屏",
             "360": "360 全景片段（会按原始 2:1 画面渲染，请先导出重构图的平面 MP4）"}
    for k, n in lossy.items():
        if n:
            warnings.append(f"edit.json v1 无法表达{names[k]}（{n} 处），已丢弃；完整效果请用 `autocut render`。")
    # 字幕：时间线时间 → 源素材时间
    for cue in edl.subtitles:
        mid = (cue.start + cue.end) / 2
        idx = next((i for i, (a, b) in enumerate(tl) if a <= mid < b), None)
        if idx is None:
            continue
        c, (a, _b) = edl.clips[idx], tl[idx]
        s0 = min(max(c.out_to_src(cue.start - a), c.in_), c.out)
        s1 = min(max(c.out_to_src(cue.end - a), c.in_), c.out)
        if s1 - s0 < 0.05:
            continue
        lang = "zh" if _CJK.search(cue.text) else "en"
        plan["captions"].append({"clip": idx, "start": round(s0, 3), "end": round(s1, 3), lang: cue.text})
    music = next((a for a in edl.audio if a.kind == "music"), None)
    if music:
        msrc = Path(music.src)
        if not msrc.is_absolute():
            msrc = project.root / msrc
        plan["music"] = {"source": _rel(msrc, base), "volume": round(min(2.0, music.volume), 3),
                         "original_volume": 1, "fade_in": music.fade_in, "fade_out": music.fade_out}
        if music.duck:
            warnings.append("配乐闪避（ducking）无法写进 edit.json；toolkit 的 `mix` 命令支持闪避，可对旁白版本再混音。")
    if any(a.kind == "voiceover" for a in edl.audio):
        warnings.append("旁白轨未导出：用 toolkit 的 `narrate` / `mix` 装配旁白。")
    if any(a.kind == "sfx" for a in edl.audio):
        warnings.append("自动音效轨未导出（edit.json v1 只有一条配乐）。")
    if edl.overlays:
        warnings.append(f"{len(edl.overlays)} 条标题/章节/Callout 文字不在 edit.json v1 范围内，已丢弃。")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return plan, warnings


# ------------------------------------------------------------------ import edit.json
def import_edit(project: Project, plan_path: Path, *, mode: str = "ref", style: str | None = None) -> tuple[EDL, list[str]]:
    from .ingest import ingest

    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    if plan.get("version") != 1 or not plan.get("clips"):
        raise ValueError("不是 toolkit edit.json（需要 version: 1 且有 clips）")
    base = plan_path.resolve().parent
    notes: list[str] = []

    def resolve(p: str) -> Path:
        q = Path(p).expanduser()
        return (q if q.is_absolute() else base / q).resolve()

    sources = [resolve(c["source"]) for c in plan["clips"]]
    missing = [s for s in sources if not s.is_file()]
    if missing:
        raise FileNotFoundError(f"素材不存在：{missing[0]}")
    music_path = resolve(plan["music"]["source"]) if plan.get("music") else None
    ingest(project, sorted({*sources, *([music_path] if music_path else [])}), mode=mode)
    media = project.media()
    by_key = {(m["source_name"], m["size"]): m for m in media}

    def find(path: Path) -> dict:
        return by_key[(path.name, path.stat().st_size)]

    out = plan.get("output") or {}
    w, h = int(out.get("width", 1920)), int(out.get("height", 1080))
    pdata = project.load()
    edl = EDL(planner="import:edit.json", project=pdata.get("name", ""), title=plan.get("title", ""),
              type=pdata.get("type", ""), width=w, height=h, fps=int(out.get("fps", 30)),
              aspect=_aspect_of(w, h), style=style or pdata.get("style", ""))
    from .plan.common import apply_style_meta
    apply_style_meta(edl, project)
    edl.width, edl.height = w, h
    starts: list[float] = []
    t = 0.0
    for i, c in enumerate(plan["clips"]):
        m = find(sources[i])
        clip = Clip(id=f"c{i + 1:03d}", media_id=m["id"], src=str(project.media_path(m)), **{"in": float(c["in"])},
                    out=float(c["out"]), role=m.get("role") if m.get("kind") == "video" else "broll",
                    note=str(c.get("reason", "")), projection=m.get("projection", "flat"))
        if clip.role in ("video", "auto", ""):
            clip.role = "broll"
        edl.clips.append(clip)
        starts.append(t)
        t += clip.duration
    for cap in plan.get("captions") or []:
        ci = int(cap["clip"])
        c = edl.clips[ci]
        a = starts[ci] + (float(cap["start"]) - c.in_)
        b = starts[ci] + (float(cap["end"]) - c.in_)
        text = cap.get("zh") or cap.get("en") or ""
        if text:
            edl.subtitles.append(SubtitleCue(start=round(a, 3), end=round(b, 3), text=text))
        if cap.get("zh") and cap.get("en"):
            notes.append("同一条字幕有 zh/en 两种语言：autocut 只带入 zh；英文请另做一版。")
    if music_path:
        mm = plan["music"]
        edl.audio.append(AudioItem(kind="music", src=str(project.media_path(find(music_path))), start=0,
                                   duration=round(t, 3), volume=float(mm.get("volume", 0.12)),
                                   fade_in=float(mm.get("fade_in", 0)), fade_out=float(mm.get("fade_out", 0)), duck=True))
    edl.notes.append("由 toolkit edit.json 导入：没有运镜/特效/转场；可在 edl.json 里手加，或用 `autocut plan` 重新规划。")
    edl.normalize_transitions()
    return edl, notes


def save_edl(project: Project, edl: EDL) -> Path:
    if project.edl_path.exists():
        hist = project.root / "analysis" / "edl_history"
        hist.mkdir(parents=True, exist_ok=True)
        n = len(list(hist.glob("edl_*.json"))) + 1
        project.edl_path.replace(hist / f"edl_{n:03d}.json")
    edl.save(project.edl_path)
    return project.edl_path


# ------------------------------------------------------------------ inspect manifest
def import_index(project: Project, manifest: Path, *, mode: str = "ref") -> dict:
    """toolkit `inspect` 的 manifest.json：把索引到的视频入库（不复制，默认只引用原路径）。"""
    from .ingest import ingest

    data = json.loads(Path(manifest).read_text(encoding="utf-8"))
    files = [Path(f["source"]) for f in data.get("files") or [] if f.get("source")]
    present = [f for f in files if f.is_file()]
    for f in files:
        if f not in present:
            warn(f"索引里的文件已不在原位置，跳过：{f.name}")
    if not present:
        raise FileNotFoundError("manifest 里没有可用的本地视频文件")
    return ingest(project, present, mode=mode)


# ------------------------------------------------------------------ transcripts
def convert_transcript(data: dict) -> dict | None:
    """toolkit transcript.json → vcut 的 {"language","model","device","segments"}。无音频/无语音返回 None。"""
    segs = []
    for s in data.get("segments") or []:
        text = str(s.get("text", "")).strip()
        if text and float(s.get("end", 0)) > float(s.get("start", 0)):
            segs.append({"start": round(float(s["start"]), 3), "end": round(float(s["end"]), 3), "text": text,
                         "no_speech_prob": round(float(s.get("no_speech_prob") or 0.0), 3)})
    if not segs:
        return None
    return {"language": data.get("language", ""), "model": data.get("model", "toolkit"), "device": "toolkit",
            "segments": segs}


def imported_transcript_dir(project: Project) -> Path:
    return project.analysis_dir / "transcripts_in"


def import_transcript(project: Project, media_ref: str, transcript: Path) -> Path:
    item = next((m for m in project.media() if media_ref in (m["id"], m["source_name"])), None)
    if not item:
        raise KeyError(f"项目里没有这个素材：{media_ref}")
    data = json.loads(Path(transcript).read_text(encoding="utf-8"))
    if "segments" not in data:
        raise ValueError("不是 toolkit transcript.json（缺少 segments）")
    dst = imported_transcript_dir(project) / f"{item['id']}.json"
    write_json(dst, data)
    return dst


def load_imported_transcript(project: Project, item: dict) -> dict | None:
    p = imported_transcript_dir(project) / f"{item['id']}.json"
    if not p.exists():
        return None
    return convert_transcript(read_json(p, {}))


def toolkit_transcribe(wav: Path, cfg: dict) -> dict | None:
    """asr.engine = toolkit：调用 video/scripts/transcribe.py（本地离线，除非 asr.allow_download）。"""
    vd = toolkit_video_dir()
    if vd is None:
        raise RuntimeError("找不到 toolkit 的 video/scripts/transcribe.py（asr.engine: toolkit 只在 skill 目录内可用）")
    model = os.environ.get("VCUT_ASR_MODEL") or cfg.get("toolkit_model") or cfg.get("cpu_model", "small")
    device = os.environ.get("VCUT_ASR_DEVICE") or cfg.get("device", "auto")
    if device == "auto":
        try:
            import ctranslate2
            device = "cuda" if ctranslate2.get_cuda_device_count() > 0 else "cpu"
        except Exception:  # noqa: BLE001
            device = "cpu"
    out = wav.with_suffix(".toolkit.json")
    out.unlink(missing_ok=True)
    cmd = [sys.executable, str(vd / "scripts" / "transcribe.py"), str(wav), "--out", str(out), "--model", str(model),
           "--device", device, "--compute-type", "float16" if device == "cuda" else "int8"]
    lang = cfg.get("language", "auto")
    if lang not in ("auto", "", None):
        cmd += ["--language", str(lang)]
    if cfg.get("allow_download"):
        cmd.append("--download")
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout).strip()[-400:])
    return convert_transcript(json.loads(out.read_text(encoding="utf-8")))


# ------------------------------------------------------------------ narration
def import_narration(project: Project, edl: EDL, narr_dir: Path) -> list[str]:
    """toolkit `narrate` 输出目录（narration.wav、zh.srt/en.srt）→ EDL 旁白轨 + 字幕。"""
    wav = Path(narr_dir) / "narration.wav"
    if not wav.is_file():
        raise FileNotFoundError(f"{narr_dir} 里没有 narration.wav（先运行 `run narrate`）")
    notes = []
    from .media import probe
    dur = probe(wav).duration or edl.total_duration
    edl.audio = [a for a in edl.audio if a.kind != "voiceover"]
    edl.audio.append(AudioItem(kind="voiceover", src=str(wav.resolve()), start=0, duration=round(dur, 3), volume=1.0))
    for a in edl.audio:
        if a.kind == "music":
            a.duck = True
    srt = Path(narr_dir) / ("zh.srt" if (Path(narr_dir) / "zh.srt").is_file() and (Path(narr_dir) / "zh.srt").read_text(encoding="utf-8").strip() else "en.srt")
    if srt.is_file() and srt.read_text(encoding="utf-8").strip():
        edl.subtitles = [SubtitleCue(start=a, end=b, text=t) for a, b, t in parse_srt(srt.read_text(encoding="utf-8"))]
        notes.append(f"字幕来自 {srt.name}")
    if dur > edl.total_duration + 0.5:
        notes.append(f"旁白（{dur:.1f}s）比画面（{edl.total_duration:.1f}s）长，需要加长镜头或缩短旁白。")
    return notes
