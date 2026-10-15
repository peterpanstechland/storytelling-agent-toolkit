"""vcut analyze: incremental per-media analysis cached as analysis/<media_id>.json."""
from __future__ import annotations

from pathlib import Path

from .. import config
from ..backends import BackendError, backend_name_for, get_backend
from ..media import extract_audio_wav, extract_frame, make_proxy
from ..project import Project
from ..util import info, ok, read_json, warn, write_json
from . import audio as A
from . import signals as S
from . import vision as V

ANALYSIS_VERSION = 2


def analysis_path(project: Project, media_id: str) -> Path:
    return project.analysis_dir / f"{media_id}.json"


def _fingerprint(project: Project, item: dict) -> str:
    p = project.media_path(item)
    try:
        st = p.stat()
        return f"{st.st_size}-{int(st.st_mtime)}"
    except OSError:
        return "missing"


def analyze_media(project: Project, item: dict, *, backend=None, force: bool = False,
                  redo_vision: bool = False, do_asr: bool = True) -> dict:
    acfg = config.settings().get("analysis") or {}
    src = project.media_path(item)
    apath = analysis_path(project, item["id"])
    fp = _fingerprint(project, item)
    data = read_json(apath, None) if not force else None
    if not data or data.get("version") != ANALYSIS_VERSION or data.get("fingerprint") != fp:
        data = {"version": ANALYSIS_VERSION, "media_id": item["id"], "fingerprint": fp, "stages": {}}
    stages = data["stages"]
    pinfo = item.get("probe") or {}
    duration = float(pinfo.get("duration") or 0)
    data["duration"] = duration
    rel = lambda p: Path(p).relative_to(project.root).as_posix()  # noqa: E731

    # 1) scenes + quality (single decode pass)
    if not stages.get("scan"):
        info(f"  · 镜头切分 + 画质分析：{item['source_name']}")
        scan = S.scan_video(src, pinfo.get("display_width") or 0, pinfo.get("display_height") or 0,
                            scene_threshold=float(acfg.get("scene_threshold", 0.32)),
                            sample_fps=float(acfg.get("sample_fps", 3)), hwaccel=str(acfg.get("hwaccel", "auto")))
        shots = S.make_shots(duration, scan["cuts"], min_len=float(acfg.get("min_shot_seconds", 0.6)),
                             max_len=float(acfg.get("max_shot_seconds", 8)))
        for s in shots:
            s["quality"] = S.shot_quality(scan["frames"], s["start"], s["end"])
            s.update(S.shot_activity(scan["frames"], s["start"], s["end"]))
        data["cuts"] = scan["cuts"]
        data["shots"] = shots
        stages["scan"] = True
        stages["keyframes"] = False
        stages["vision"] = None

    # 2) keyframes
    if not stages.get("keyframes"):
        kdir = project.analysis_dir / "keyframes"
        width = int(acfg.get("keyframe_width", 640))
        for s in data["shots"]:
            d = s["end"] - s["start"]
            times = [s["start"] + d * 0.5] if d < 4 else [s["start"] + d * 0.25, s["start"] + d * 0.75]
            frames = []
            for j, t in enumerate(times):
                out = kdir / f"{item['id']}_{s['idx']:03d}_{j}.jpg"
                try:
                    extract_frame(src, min(t, max(0.0, duration - 0.05)), out, width=width,
                                  equirect=item.get("projection") == "equirect")
                    frames.append(rel(out))
                except Exception as e:  # noqa: BLE001
                    warn(f"关键帧提取失败 {item['source_name']}@{t:.1f}s: {e}")
            s["keyframes"] = frames
        stages["keyframes"] = True

    # 3) audio activity
    if pinfo.get("has_audio") and not stages.get("audio"):
        wav = project.analysis_dir / "audio" / f"{item['id']}.wav"
        if not wav.exists():
            extract_audio_wav(src, wav)
        data["silences"] = A.detect_silences(wav, duration, float(acfg.get("silence_db", -35)))
        for s in data["shots"]:
            s["audio_activity"] = A.active_ratio(data["silences"], s["start"], s["end"])
        stages["audio"] = True

    # 4) transcription
    asr_cfg = config.settings().get("asr") or {}
    if not stages.get("transcript"):
        # 复用 toolkit `run transcribe` 的结果（autocut import-transcript），不重复转写
        from .. import bridge
        imported = bridge.load_imported_transcript(project, item)
        if imported:
            info(f"  · 使用导入的转写（toolkit transcript）：{item['source_name']}")
            data["transcript"] = imported
            stages["transcript"] = {"model": imported["model"], "device": imported["device"]}
    if pinfo.get("has_audio") and do_asr and asr_cfg.get("enabled", True) and not stages.get("transcript"):
        if A.asr_available():
            wav = project.analysis_dir / "audio" / f"{item['id']}.wav"
            if not wav.exists():
                extract_audio_wav(src, wav)
            info(f"  · 语音转写：{item['source_name']}")
            try:
                tr = A.transcribe(wav, asr_cfg)
            except Exception as e:  # noqa: BLE001 - model download/CUDA problems must not kill the pipeline
                warn(f"语音转写失败（跳过，稍后可重跑 analyze）：{str(e).splitlines()[0][:200]}")
                tr = None
            if tr:
                data["transcript"] = tr
                stages["transcript"] = {"model": tr["model"], "device": tr["device"]}
        else:
            stages.setdefault("transcript_skipped", "未安装 faster-whisper（pip install -r video/requirements-asr.txt）")
    segs = (data.get("transcript") or {}).get("segments") or []
    for s in data["shots"]:
        s["speech_ratio"] = A.speech_ratio(segs, s["start"], s["end"]) if segs else 0.0
        s["speech"] = " ".join(x["text"] for x in segs if x["end"] > s["start"] and x["start"] < s["end"])[:300]

    # 5) vision
    want_vision = backend is not None and (redo_vision or not stages.get("vision")
                                           or stages["vision"].get("model") != backend.vision_model)
    if want_vision:
        info(f"  · 画面理解（{backend.name}/{backend.vision_model}）：{item['source_name']}")
        try:
            shots_in = [{**s, "_frames": [project.root / k for k in s.get("keyframes", [])], "_speech": s.get("speech", "")}
                        for s in data["shots"]]
            if backend.supports_video() and duration > 0:
                proxy = project.analysis_dir / "proxies" / f"{item['id']}.mp4"
                if not proxy.exists():
                    make_proxy(src, proxy)
                res = V.describe_video(backend, project.load(), item, proxy, shots_in)
            else:
                res = V.describe_shots(backend, project.load(), item, shots_in,
                                       batch=int(acfg.get("vision_batch", 6)))
            for s in data["shots"]:
                if s["idx"] in res:
                    s["vision"] = res[s["idx"]]
            stages["vision"] = {"backend": backend.name, "model": backend.vision_model, "n": len(res)}
        except BackendError as e:
            warn(f"画面理解失败（继续用启发式）：{e}")

    write_json(apath, data)
    return data


def analyze_project(project: Project, *, backend_name: str | None = None, force: bool = False,
                    redo_vision: bool = False, only: list[str] | None = None, do_asr: bool = True) -> list[dict]:
    pdata = project.load()
    bname = backend_name_for(pdata, backend_name)
    try:
        backend = get_backend(bname)
    except BackendError as e:
        warn(f"{e}；本次不做画面理解，改用启发式。")
        backend = None
    if backend:
        backend.image_width = int((config.settings().get("analysis") or {}).get("vision_image_width", 512))
    media = [m for m in project.media() if m["kind"] == "video" and not m.get("needs_export")]
    if only:
        media = [m for m in media if m["id"] in only or m["source_name"] in only]
    if not media:
        warn("项目里没有可分析的视频，先 `autocut ingest`。")
        return []
    if not A.asr_available() and do_asr:
        warn("未安装 faster-whisper，跳过语音转写（字幕/口播识别会变弱）。安装：pip install -r video/requirements-asr.txt")
    info(f"分析 {len(media)} 个视频（后端：{backend.name if backend else '离线启发式'}）…")
    results = []
    for m in media:
        if not project.media_path(m).exists():
            warn(f"文件不存在，跳过：{m['path']}")
            continue
        results.append(analyze_media(project, m, backend=backend, force=force, redo_vision=redo_vision, do_asr=do_asr))
    # separately recorded voiceover (audio files) -> transcript only, used for subtitles
    if do_asr and A.asr_available():
        for m in project.media():
            if m["kind"] != "audio" or m.get("role") != "voiceover" or not project.media_path(m).exists():
                continue
            apath = analysis_path(project, m["id"])
            fp = _fingerprint(project, m)
            old = read_json(apath, None)
            if old and old.get("fingerprint") == fp and old.get("transcript") and not force:
                continue
            wav = project.analysis_dir / "audio" / f"{m['id']}.wav"
            extract_audio_wav(project.media_path(m), wav)
            info(f"  · 旁白转写：{m['source_name']}")
            try:
                tr = A.transcribe(wav, config.settings().get("asr") or {})
            except Exception as e:  # noqa: BLE001
                warn(f"旁白转写失败：{str(e).splitlines()[0][:200]}")
                continue
            write_json(apath, {"version": ANALYSIS_VERSION, "media_id": m["id"], "fingerprint": fp, "kind": "audio",
                               "duration": float((m.get("probe") or {}).get("duration") or 0), "transcript": tr,
                               "stages": {"transcript": True}})
    ok(f"分析完成：{sum(len(r.get('shots', [])) for r in results)} 个镜头，结果在 {project.analysis_dir}")
    return results
