"""Silence detection (ffmpeg) and transcription (faster-whisper, optional extra)."""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

from ..media import ffmpeg
from ..util import warn

_SIL_START = re.compile(r"silence_start: (-?[0-9.]+)")
_SIL_END = re.compile(r"silence_end: (-?[0-9.]+)")


def detect_silences(wav: Path, duration: float, noise_db: float = -35, min_dur: float = 0.5) -> list[list[float]]:
    proc = ffmpeg(["-i", str(wav), "-af", f"silencedetect=n={noise_db}dB:d={min_dur}", "-f", "null", "-"])
    txt = proc.stderr.decode("utf-8", "replace")
    out, cur = [], None
    for line in txt.splitlines():
        m = _SIL_START.search(line)
        if m:
            cur = max(0.0, float(m.group(1)))
            continue
        m = _SIL_END.search(line)
        if m and cur is not None:
            out.append([round(cur, 3), round(float(m.group(1)), 3)])
            cur = None
    if cur is not None:
        out.append([round(cur, 3), round(duration, 3)])
    return out


def active_ratio(silences: list[list[float]], start: float, end: float) -> float:
    if end <= start:
        return 0.0
    sil = sum(max(0.0, min(e, end) - max(s, start)) for s, e in silences)
    return round(1.0 - sil / (end - start), 3)


def speech_ratio(segments: list[dict], start: float, end: float) -> float:
    if end <= start:
        return 0.0
    cov = sum(max(0.0, min(s["end"], end) - max(s["start"], start)) for s in segments)
    return round(min(1.0, cov / (end - start)), 3)


def _add_windows_cuda_dlls() -> None:
    """pip-installed nvidia-cublas/cudnn wheels put DLLs under site-packages/nvidia/*/bin."""
    if sys.platform != "win32":
        return
    for base in map(Path, sys.path):
        nv = base / "nvidia"
        if not nv.is_dir():
            continue
        for b in nv.glob("*/bin"):
            try:
                os.add_dll_directory(str(b))  # type: ignore[attr-defined]
            except (OSError, AttributeError):
                pass
            os.environ["PATH"] = str(b) + os.pathsep + os.environ.get("PATH", "")


_MODEL_CACHE: dict = {}


def asr_available() -> bool:
    try:
        import faster_whisper  # noqa: F401
        return True
    except ImportError:
        return False


def transcribe(wav: Path, cfg: dict) -> dict | None:
    """Return {"language", "model", "device", "segments":[{start,end,text}]} or None if ASR unavailable."""
    if not asr_available():
        return None
    if cfg.get("engine") == "toolkit":  # 交给 toolkit 的 transcribe.py（单一实现，本地离线）
        from .. import bridge
        return bridge.toolkit_transcribe(wav, cfg)
    _add_windows_cuda_dlls()
    # 国内网络：settings.yaml → asr.hf_endpoint: https://hf-mirror.com （或环境变量 HF_ENDPOINT）
    if cfg.get("hf_endpoint") and not os.environ.get("HF_ENDPOINT"):
        os.environ["HF_ENDPOINT"] = str(cfg["hf_endpoint"])
    from faster_whisper import WhisperModel

    device = os.environ.get("VCUT_ASR_DEVICE") or cfg.get("device", "auto")
    if device == "auto":
        try:
            import ctranslate2
            device = "cuda" if ctranslate2.get_cuda_device_count() > 0 else "cpu"
        except Exception:  # noqa: BLE001
            device = "cpu"
    model_name = os.environ.get("VCUT_ASR_MODEL") or (cfg.get("model", "large-v3-turbo") if device == "cuda"
                                                       else cfg.get("cpu_model", "small"))
    key = (model_name, device)
    if key not in _MODEL_CACHE:
        try:
            if device == "cuda":
                _MODEL_CACHE[key] = WhisperModel(model_name, device="cuda", device_index=int(cfg.get("device_index", 0)),
                                                 compute_type="float16")
            else:
                _MODEL_CACHE[key] = WhisperModel(model_name, device="cpu", compute_type="int8")
        except Exception as e:  # noqa: BLE001
            if device == "cuda":
                warn(f"CUDA 加载 Whisper 失败（{e}），改用 CPU。检查 cuBLAS/cuDNN 是否安装（pip 安装 nvidia-cublas-cu12 与 nvidia-cudnn-cu12）。")
                device = "cpu"
                model_name = cfg.get("cpu_model", "small")
                key = (model_name, device)
                _MODEL_CACHE[key] = WhisperModel(model_name, device="cpu", compute_type="int8")
            else:
                raise
    model = _MODEL_CACHE[key]
    lang = cfg.get("language", "auto")
    seg_iter, info = model.transcribe(
        str(wav), language=None if lang in ("auto", "", None) else lang, vad_filter=True,
        initial_prompt=cfg.get("initial_prompt") or None, beam_size=5, condition_on_previous_text=False,
    )
    segs = []
    for s in seg_iter:
        text = (s.text or "").strip()
        if text:
            segs.append({"start": round(s.start, 3), "end": round(s.end, 3), "text": text,
                         "no_speech_prob": round(getattr(s, "no_speech_prob", 0.0) or 0.0, 3)})
    return {"language": info.language, "model": model_name, "device": device, "segments": segs}
