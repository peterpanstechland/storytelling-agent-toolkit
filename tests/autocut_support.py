"""autocut（video/autocut）测试的公共支持：路径、依赖检查、合成素材与小工具。

只使用 FFmpeg 生成的合成素材和模拟 HTTP，不读取任何真实素材或账号。
缺少 autocut 基础依赖（requirements-autocut.txt）或 ffmpeg 时，相关测试模块整体跳过。
"""
from __future__ import annotations

import atexit
import builtins  # noqa: F401  (tests monkeypatch builtins.__import__)
import contextlib
import importlib
import importlib.util
import os
import shutil
import sys
import tempfile
import unittest
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AUTOCUT = ROOT / "skills/storytelling/video/autocut"
CORE_MODULES = ("typer", "rich", "yaml", "pydantic", "httpx", "numpy", "cv2")
_TMP_ROOT: list[Path] = []

for _p in (AUTOCUT, AUTOCUT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def require_autocut(need_ffmpeg: bool = False) -> None:
    missing = [m for m in CORE_MODULES if importlib.util.find_spec(m) is None]
    if missing:
        raise unittest.SkipTest("autocut dependencies missing: " + ", ".join(missing))
    if need_ffmpeg and not shutil.which("ffmpeg"):
        raise unittest.SkipTest("ffmpeg not installed")


def importorskip(name: str):
    try:
        return importlib.import_module(name)
    except ImportError:
        raise unittest.SkipTest(f"{name} not installed") from None


def _session_tmp() -> Path:
    if not _TMP_ROOT:
        root = Path(tempfile.mkdtemp(prefix="autocut-tests-"))
        _TMP_ROOT.append(root)
        atexit.register(shutil.rmtree, root, True)
    return _TMP_ROOT[0]


def tmp_path_factory(self: unittest.TestCase) -> Path:
    """Use as a TestCase method: a fresh directory removed after the test."""
    d = Path(tempfile.mkdtemp(prefix="case-", dir=_session_tmp()))
    self.addCleanup(shutil.rmtree, d, True)
    return d


class MonkeyPatch:
    def __init__(self):
        self._undo = []

    def setattr(self, obj, name, value):
        self._undo.append((setattr, obj, name, getattr(obj, name)))
        setattr(obj, name, value)

    def setenv(self, name, value):
        old = os.environ.get(name)
        self._undo.append((_restore_env, name, old, None))
        os.environ[name] = value

    def delenv(self, name, raising=True):
        old = os.environ.get(name)
        if old is None and raising:
            raise KeyError(name)
        self._undo.append((_restore_env, name, old, None))
        os.environ.pop(name, None)

    def undo(self):
        for fn, a, b, c in reversed(self._undo):
            fn(a, b, c)
        self._undo.clear()


def _restore_env(name, old, _unused):
    if old is None:
        os.environ.pop(name, None)
    else:
        os.environ[name] = old


def monkeypatch_factory(self: unittest.TestCase) -> MonkeyPatch:
    mp = MonkeyPatch()
    self.addCleanup(mp.undo)
    return mp


@contextlib.contextmanager
def raises(exc):
    try:
        yield
    except exc:
        return
    raise AssertionError(f"{exc.__name__} not raised")


class approx:
    def __init__(self, expected, abs=None, rel=1e-6):
        self.expected, self.abs_tol, self.rel = expected, abs, rel

    def __eq__(self, other):
        tol = self.abs_tol if self.abs_tol is not None else max(1e-12, self.rel * builtins.abs(self.expected))
        return builtins.abs(other - self.expected) <= tol

    def __repr__(self):
        return f"approx({self.expected})"


# ------------------------------------------------------------------ synthetic media / project
@lru_cache(maxsize=1)
def media_dir() -> Path:
    if not shutil.which("ffmpeg"):
        raise unittest.SkipTest("ffmpeg not installed")
    import importlib.util as u
    spec = u.spec_from_file_location("make_test_media", AUTOCUT / "scripts" / "make_test_media.py")
    mod = u.module_from_spec(spec)
    spec.loader.exec_module(mod)
    d = _session_tmp() / "media"
    d.mkdir()
    mod.make(d, small=True)
    return d


TALK = [
    {"start": 0.2, "end": 3.6, "text": "Hello everyone, welcome back to my channel."},
    {"start": 4.3, "end": 8.4, "text": "Today I will show you my new maker project, a smart desk lamp."},
    {"start": 9.1, "end": 13.4, "text": "It uses an ESP32 and a light sensor to adjust brightness."},
    {"start": 14.0, "end": 17.5, "text": "Let me show you how I built it."},
]


def write_fake_transcript(project, source_name: str, segments: list[dict]) -> None:
    """Inject a transcript as if faster-whisper had run (keeps tests offline/deterministic)."""
    from vcut.util import read_json, write_json

    m = next(m for m in project.media() if m["source_name"] == source_name)
    p = project.analysis_dir / f"{m['id']}.json"
    d = read_json(p)
    d["transcript"] = {"language": "en", "model": "fake", "device": "cpu", "segments": segments}
    d["stages"]["transcript"] = {"model": "fake"}
    for s in d["shots"]:
        cov = sum(max(0, min(x["end"], s["end"]) - max(x["start"], s["start"])) for x in segments)
        s["speech_ratio"] = round(min(1.0, cov / (s["end"] - s["start"])), 3)
        s["speech"] = " ".join(x["text"] for x in segments if x["end"] > s["start"] and x["start"] < s["end"])
    write_json(p, d)


@lru_cache(maxsize=1)
def analyzed_project():
    """A maker project with all synthetic media ingested + analyzed (no ASR, fake transcript)."""
    from vcut.analyze import analyze_project
    from vcut.ingest import ingest
    from vcut.project import Project

    mdir = media_dir()
    root = _session_tmp() / "projects"
    root.mkdir()
    p = Project.create("测试台灯", "maker", parent=root, duration=30)
    d = p.load()
    d["theme"] = "ESP32 自动调光台灯"
    d["maker"]["features"] = ["自动调光", "手势开关"]
    p.save(d)
    ingest(p, [mdir], mode="copy")
    analyze_project(p, do_asr=False)
    write_fake_transcript(p, "VID20260301103000.mp4", TALK)
    return p
