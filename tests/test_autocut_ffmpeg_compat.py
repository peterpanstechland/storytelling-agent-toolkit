"""ffmpeg version-dependent option syntax (`-/filter_complex file` needs ffmpeg 7; older uses -filter_complex_script)."""
import subprocess
import unittest
from unittest import mock

import autocut_support as S

S.require_autocut()

from vcut import media


def fake_run(text):
    return lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout=text.encode(), stderr=b"")


class TestFfmpegCompat(unittest.TestCase):
    def setUp(self):
        media.ffmpeg_major.cache_clear()
        media.xfade_transitions.cache_clear()

    def tearDown(self):
        media.ffmpeg_major.cache_clear()
        media.xfade_transitions.cache_clear()

    def test_major_parsing(self):
        for text, want in [("ffmpeg version 6.1.1-3ubuntu5 Copyright", 6), ("ffmpeg version 7.1.5-0+deb13u1", 7),
                           ("ffmpeg version n6.0 Copyright", 6), ("ffmpeg version 4.2.2-static", 4),
                           ("ffmpeg version N-117000-gabcdef", 99), ("garbage", 0)]:
            media.ffmpeg_major.cache_clear()
            with mock.patch.object(media.subprocess, "run", fake_run(text)):
                self.assertEqual(media.ffmpeg_major("ffx"), want, text)

    def test_major_is_cached(self):
        calls = []

        def run(*a, **k):
            calls.append(a)
            return fake_run("ffmpeg version 6.1")()
        with mock.patch.object(media.subprocess, "run", run):
            media.ffmpeg_major("ffy")
            media.ffmpeg_major("ffy")
        self.assertEqual(len(calls), 1)

    def test_missing_binary(self):
        with mock.patch.object(media.subprocess, "run", side_effect=FileNotFoundError):
            self.assertEqual(media.ffmpeg_major("nope"), 0)

    def test_xfade_fallback_uses_capabilities_not_version(self):
        help_text = "     fade    0    ..FV....... fade transition\n     wipeleft 1 ..FV....... wipe\n"
        with mock.patch.object(media.subprocess, "run", fake_run(help_text)):
            self.assertEqual(media.compatible_xfade("zoomin", "old-build"), "fade")
            self.assertEqual(media.compatible_xfade("wipeleft", "old-build"), "wipeleft")
        with mock.patch.object(media.subprocess, "run", fake_run(help_text + "     zoomin 43 ..FV....... zoom\n")):
            self.assertEqual(media.compatible_xfade("zoomin", "new-build"), "zoomin")
        with mock.patch.object(media.subprocess, "run", fake_run("Unknown filter 'xfade'")):
            with self.assertRaises(media.FFmpegError):
                media.compatible_xfade("fade", "missing-filter")

    def test_file_option(self):
        self.assertEqual(media.file_option("filter_complex", "g.txt", major=7), ["-/filter_complex", "g.txt"])
        self.assertEqual(media.file_option("filter_complex", "g.txt", major=6), ["-filter_complex_script", "g.txt"])
        self.assertEqual(media.file_option("vf", "g.txt", major=5), ["-filter_script:v", "g.txt"])
        self.assertEqual(media.file_option("af", "g.txt", major=6), ["-filter_script:a", "g.txt"])
        with self.assertRaises(media.FFmpegError):
            media.file_option("metadata", "m.txt", major=6)

    def test_file_option_uses_detected_version(self):
        with mock.patch.object(media, "ffmpeg_major", return_value=6):
            self.assertEqual(media.file_option("filter_complex", "g.txt")[0], "-filter_complex_script")
        with mock.patch.object(media, "ffmpeg_major", return_value=7):
            self.assertEqual(media.file_option("filter_complex", "g.txt")[0], "-/filter_complex")


if __name__ == "__main__":
    unittest.main()
