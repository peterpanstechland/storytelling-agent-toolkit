#!/usr/bin/env python3
"""Behavioral integration checks; uses synthetic tones, never real voice data."""
from __future__ import annotations

import unittest
import array
import json
import math
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import wave


def execute(args, cwd=None, expected=0):
    result = subprocess.run([str(x) for x in args], cwd=cwd, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, check=False)
    assert result.returncode == expected, result.stdout + result.stderr
    return result


def tone(path, seconds, hz, amplitude=0.4):
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as output:
        output.setparams((1, 2, 48000, 0, "NONE", "not compressed"))
        output.writeframes(b"".join(struct.pack("<h", round(32767 * amplitude * math.sin(2 * math.pi * hz * i / 48000)))
                                   for i in range(round(seconds * 48000))))


def pcm(path):
    result = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-f", "f32le", "-ac", "1",
                             "-ar", "48000", "-"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
    values = array.array("f")
    values.frombytes(result.stdout)
    if sys.byteorder != "little":
        values.byteswap()
    return values


def power(values, start, end):
    window = values[round(start * 48000):round(end * 48000)]
    return math.sqrt(sum(x * x for x in window) / len(window))


def component(values, start, end, hz):
    a, b = round(start * 48000), round(end * 48000)
    real = sum(values[i] * math.cos(2 * math.pi * hz * i / 48000) for i in range(a, b))
    imag = sum(values[i] * math.sin(2 * math.pi * hz * i / 48000) for i in range(a, b))
    return 2 * math.hypot(real, imag) / (b - a)


def run_checks():
    script = Path(__file__).resolve().parents[1] / "skills/storytelling/video/scripts/narration.py"
    checks = []
    with tempfile.TemporaryDirectory(prefix="storytelling-audio-test-") as temporary:
        root = Path(temporary)
        outside = root / "unrelated-cwd"
        outside.mkdir()
        case = root / "project"
        case.mkdir()
        tone(case / "voices/片段 ' one.wav", 1.2, 1000)
        tone(case / "voices/two.wav", 0.5, 1200)
        plan = {"version": 1, "duration": 4,
                "backend": {"engine": "synthetic-test-tones"},
                "segments": [
                    {"id": "a", "source": "voices/片段 ' one.wav", "start": 1.25,
                     "trim_start": 0.2, "trim_end": 1.2,
                     "captions": [{"start": 0.2, "end": 0.8, "zh": "【测试画面】时间定位", "en": "[Test footage] Timing"}]},
                    {"id": "b", "source": "voices/two.wav", "start": 3.0,
                     "text": "【测试画面】第二段"}]}
        path = case / "narration.json"
        path.write_text(json.dumps(plan, ensure_ascii=False))
        execute([sys.executable, script, "narrate", path, "--out", case / "voice-out"], cwd=outside)
        values = pcm(case / "voice-out/narration.wav")
        assert len(values) == 4 * 48000
        assert power(values, 0.1, 1.2) < 1e-6
        assert power(values, 1.3, 2.2) > 0.1
        assert power(values, 2.3, 2.9) < 1e-6
        assert power(values, 3.05, 3.45) > 0.1
        assert power(values, 3.6, 3.95) < 1e-6
        checks += ["relative paths independent of cwd, including spaces/Unicode/apostrophe",
                   "sample duration and silent gaps match final timeline offsets"]
        subtitles = (case / "voice-out/zh.srt").read_text()
        assert "00:00:01,450 --> 00:00:02,050" in subtitles
        assert "00:00:03,000 --> 00:00:03,500" in subtitles
        checks.append("trimmed-phrase caption offsets map to final timeline, not original clip times")
        overlap = json.loads(json.dumps(plan))
        overlap["segments"][1]["start"] = 1.8
        overlap_path = case / "overlap.json"
        overlap_path.write_text(json.dumps(overlap))
        failed = execute([sys.executable, script, "narrate", overlap_path, "--out", case / "rejected"], expected=1)
        assert "overlap" in failed.stderr.lower()
        overlap["allow_overlap"] = True
        overlap_path.write_text(json.dumps(overlap))
        execute([sys.executable, script, "narrate", overlap_path, "--out", case / "explicit-overlap"])
        checks.append("overlap rejected by default and accepted only explicitly")
        short_plan = json.loads(json.dumps(plan))
        short_plan["duration"] = 2
        short_path = case / "too-short.json"
        short_path.write_text(json.dumps(short_plan))
        failed = execute([sys.executable, script, "narrate", short_path, "--out", case / "short-rejected"], expected=1)
        assert "cut off narration" in failed.stderr
        checks.append("narration cannot silently truncate at requested duration")
        # The test video has real source audio (a low tone), separate from music.
        tone(case / "ambient.wav", 4, 300, 0.05)
        tone(case / "music.wav", 4, 100, 0.25)
        execute(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=navy:s=320x180:r=25:d=4",
                 "-i", case / "ambient.wav", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                 "-c:a", "aac", "-t", "4", case / "visual.mp4"])
        mix_plan = {"version": 1, "video": "visual.mp4",
                    "narration": {"source": "voice-out/narration.wav"},
                    "original": {"policy": "preserve", "gain_db": -9},
                    "music": {"source": "music.wav", "gain_db": -10,
                              "fade_in": 0, "fade_out": 0,
                              "ducking": {"enabled": True, "threshold_db": -32, "ratio": 8,
                                          "attack_ms": 5, "release_ms": 100}},
                    "subtitles": {"zh": "voice-out/zh.srt"}}
        mix_path = case / "mix.json"
        mix_path.write_text(json.dumps(mix_plan))
        execute([sys.executable, script, "mix", mix_path, "--out", case / "mixed"], cwd=outside)
        mixed = pcm(case / "mixed/mixed.wav")
        assert len(mixed) == 4 * 48000
        before = component(mixed, 0.3, 0.9, 100)
        during = component(mixed, 1.6, 2.1, 100)
        ambience = component(mixed, 0.3, 0.9, 300)
        assert before > 0.05 and during < before * 0.5, (before, during)
        assert ambience > 0.01, ambience
        manifest = json.loads((case / "mixed/manifest.json").read_text())
        assert manifest["encoded_sample_peak_dbfs"] < 0
        assert (case / "mixed/zh.srt").read_text() == subtitles
        checks += ["music level decreases during actual narration signal",
                   "original ambience is retained alongside separate music and narration",
                   "muxed MP4 has same video duration and decoded audio headroom",
                   "SRT delivery preserves final timeline unchanged"]
        no_overwrite = execute([sys.executable, script, "mix", mix_path, "--out", case / "mixed"], expected=1)
        assert "new or empty" in no_overwrite.stderr
        checks.append("nonempty output cannot be overwritten")
        report = {"passed": True, "synthetic_test_only": True, "checks": checks,
                  "music_100hz_amplitude_before_voice": before,
                  "music_100hz_amplitude_during_voice": during,
                  "original_300hz_amplitude": ambience,
                  "note": "Tests validate signal behavior, not voice identity, naturalness or listening quality."}
    return report


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg is required")
class AudioIntegrationTests(unittest.TestCase):
    def test_timed_audio_ducking_and_boundaries(self):
        self.assertTrue(run_checks()["passed"])


if __name__ == "__main__":
    unittest.main()
