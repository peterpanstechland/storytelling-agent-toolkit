"""Sound effects: a local SFX library folder (like the music library) with procedural fallbacks.

Library layout (settings.yaml → sfx.library or env VCUT_SFX_LIBRARY):
    <library>/whoosh/*.wav|mp3   <library>/hit/…   <library>/riser/…   <library>/glitch/…
    <library>/shutter/…          <library>/pop/…
Anything missing is synthesised with NumPy (no samples, no licensing questions) and cached as WAV.
"""
from __future__ import annotations

import math
import os
import wave
from pathlib import Path

import numpy as np

from .. import config
from ..util import short_hash

SR = 48000
KINDS = ("whoosh", "hit", "riser", "glitch", "shutter", "pop", "swish")
AUDIO_EXT = {".wav", ".mp3", ".flac", ".m4a", ".aac", ".ogg"}


def library_dir() -> Path | None:
    p = os.environ.get("VCUT_SFX_LIBRARY") or (config.settings().get("sfx") or {}).get("library") or ""
    return Path(p) if p and Path(p).is_dir() else None


def _write(path: Path, stereo: np.ndarray) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = np.clip(stereo, -1, 1)
    pcm = (data * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.T.copy().tobytes())
    return path


def _bandpass_sweep(noise: np.ndarray, f0: np.ndarray, q: float = 1.6) -> np.ndarray:
    """Time-varying resonant band-pass (state-variable filter), f0 per sample (Hz)."""
    out = np.empty_like(noise)
    low = band = 0.0
    damp = 1.0 / q
    for i, x in enumerate(noise):
        f = 2.0 * math.sin(math.pi * min(f0[i], SR / 6) / SR)
        low += f * band
        high = x - low - damp * band
        band += f * high
        out[i] = band
    return out


def _env(n: int, attack: float, peak_at: float = 0.6, release_pow: float = 2.0) -> np.ndarray:
    x = np.linspace(0, 1, n)
    up = np.clip(x / max(peak_at, 1e-3), 0, 1) ** attack
    down = np.clip((1 - x) / max(1 - peak_at, 1e-3), 0, 1) ** release_pow
    return np.where(x < peak_at, up, down)


def _pan(mono: np.ndarray, start: float = -0.8, end: float = 0.8) -> np.ndarray:
    p = np.linspace(start, end, len(mono))
    l = np.cos((p + 1) * math.pi / 4)
    r = np.sin((p + 1) * math.pi / 4)
    return np.stack([mono * l, mono * r])


def synth(kind: str, dur: float | None = None, seed: int = 0) -> np.ndarray:
    r = np.random.default_rng(seed)
    if kind in ("whoosh", "swish"):
        d = dur or (0.7 if kind == "whoosh" else 0.32)
        n = int(SR * d)
        noise = r.normal(0, 1, n)
        x = np.linspace(0, 1, n)
        f0 = 250 + 3200 * np.sin(np.pi * x) ** 2
        y = _bandpass_sweep(noise, f0, 1.3) * _env(n, 2.2, 0.62, 1.6)
        y = y / (np.abs(y).max() + 1e-9) * 0.9
        return _pan(y, -0.9, 0.9)
    if kind == "hit":
        d = dur or 0.9
        n = int(SR * d)
        t = np.arange(n) / SR
        f = 58 * np.exp(-t * 3.5) + 34
        body = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 4.2)
        click = r.normal(0, 1, n) * np.exp(-t * 90) * 0.6
        y = np.tanh((body + click) * 2.2) * 0.85
        return np.stack([y, y])
    if kind == "riser":
        d = dur or 1.8
        n = int(SR * d)
        t = np.arange(n) / SR
        x = t / d
        f = 180 * (2 ** (x * 2.6))
        tone = np.sin(2 * np.pi * np.cumsum(f) / SR) * 0.35 + np.sin(2 * np.pi * np.cumsum(f * 1.5) / SR) * 0.18
        noise = _bandpass_sweep(r.normal(0, 1, n), 400 + 5000 * x ** 2, 0.9) * 0.5
        y = (tone + noise / (np.abs(noise).max() + 1e-9) * 0.5) * x ** 2.2
        y[-int(SR * 0.01):] *= np.linspace(1, 0, int(SR * 0.01))
        return _pan(y / (np.abs(y).max() + 1e-9) * 0.85, -0.3, 0.3)
    if kind == "glitch":
        d = dur or 0.4
        n = int(SR * d)
        y = np.zeros(n)
        pos = 0
        while pos < n:
            ln = int(r.uniform(0.01, 0.05) * SR)
            fr = r.choice([220, 440, 880, 1760, 3520])
            seg = np.sign(np.sin(2 * np.pi * fr * np.arange(ln) / SR)) * r.uniform(0.2, 0.7)
            if r.random() < 0.4:
                seg = r.normal(0, 0.4, ln)
            seg = np.round(seg * 6) / 6  # bit crush
            y[pos:pos + ln] = seg[: n - pos]
            pos += ln + int(r.uniform(0, 0.02) * SR)
        return _pan(y * 0.7, -0.5, 0.5)
    if kind == "shutter":
        n = int(SR * 0.35)
        y = np.zeros(n)
        for at, amp in ((0.0, 1.0), (0.11, 0.7)):
            i0 = int(at * SR)
            m = int(0.03 * SR)
            y[i0:i0 + m] += r.normal(0, 1, m) * np.exp(-np.arange(m) / (0.004 * SR)) * amp
        return np.stack([y, y]) * 0.8
    if kind == "pop":
        n = int(SR * 0.25)
        t = np.arange(n) / SR
        f = 900 * np.exp(-t * 18) + 500
        y = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 22) * 0.8
        return np.stack([y, y])
    raise ValueError(kind)


def get_sfx(kind: str, cache_dir: Path, variant: int = 0, dur: float | None = None) -> Path:
    """Library file (stable choice per variant) or a generated WAV in cache_dir."""
    lib = library_dir()
    if lib:
        folder = lib / kind
        files = sorted(p for p in folder.glob("*") if p.suffix.lower() in AUDIO_EXT) if folder.is_dir() else []
        if files:
            return files[variant % len(files)].resolve()
    key = short_hash(kind, variant % 3, round(dur or 0, 2), n=8)
    path = cache_dir / f"{kind}_{key}.wav"
    if not path.exists():
        _write(path, synth(kind, dur, seed=variant % 3 + 1))
    return path.resolve()
