import shutil
import unittest

import autocut_support as S

S.require_autocut()  # 缺少 autocut 依赖时整个模块跳过

import builtins
import numpy as np
from vcut.music import detect_beats, scan_library


class AutocutMusicTests(unittest.TestCase):
    tmp_path = S.tmp_path_factory
    monkeypatch = S.monkeypatch_factory

    def test_beats_librosa_or_numpy(self):
        media_dir = S.media_dir()
        r = detect_beats(media_dir / "music" / "电子_科技" / "test_beat_120bpm.wav")
        assert 110 <= r["bpm"] <= 130
        gaps = np.diff(r["beats"])
        assert np.median(gaps) == S.approx(0.5, abs=0.05)

    def test_beats_numpy_fallback(self):
        media_dir = S.media_dir()
        monkeypatch = self.monkeypatch()
        real_import = builtins.__import__

        def no_librosa(name, *a, **k):
            if name == "librosa":
                raise ImportError
            return real_import(name, *a, **k)

        monkeypatch.setattr(builtins, "__import__", no_librosa)
        r = detect_beats(media_dir / "music" / "电子_科技" / "test_beat_120bpm.wav")
        assert r["method"] == "numpy"
        assert 115 <= r["bpm"] <= 125

    def test_scan_library_tags(self):
        media_dir = S.media_dir()
        tracks = scan_library(media_dir / "music")
        assert len(tracks) == 1
        assert "电子_科技" in tracks[0]["tags"] and tracks[0]["duration"] == S.approx(40, abs=0.5)

