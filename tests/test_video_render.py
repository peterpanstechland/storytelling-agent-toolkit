"""Rendered-media checks use only generated temporary sources, never project assets."""
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "skills/storytelling/video/run"
SPEC = importlib.util.spec_from_file_location("storytelling_render", RUN.parent / "scripts/render.py")
RENDER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RENDER)


def execute(args, cwd=None):
    return subprocess.run([str(x) for x in args], cwd=cwd, capture_output=True, text=True)


class PlanValidationTests(unittest.TestCase):
    def test_nonfinite_and_boolean_times_are_rejected(self):
        for value in (True, float("nan"), float("inf"), "1.0"):
            with self.assertRaises(RENDER.RenderError):
                RENDER.number(value, "time")

    def test_cumulative_frame_rounding_is_bounded(self):
        fps = 30000 / 1001
        total = 0
        prior = 0
        counted = 0
        for _ in range(500):
            total += 0.037
            next_boundary = RENDER.frame_boundary(total, fps)
            counted += next_boundary - prior
            prior = next_boundary
        self.assertEqual(counted, RENDER.frame_boundary(total, fps))
        self.assertLessEqual(abs(counted / fps - total), .5 / fps)


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg is required")
class RenderIntegrationTests(unittest.TestCase):
    @unittest.skipUnless(importlib.util.find_spec("PIL"), "Pillow is optional")
    def test_inspection_and_no_audio_transcription_do_not_need_a_model(self):
        with tempfile.TemporaryDirectory(prefix="storytelling-index-test-") as tmp:
            root = Path(tmp)
            source = root / "synthetic.mp4"
            made = execute(["ffmpeg", "-v", "error", "-f", "lavfi", "-i",
                            "testsrc2=s=320x180:r=25:d=1", "-c:v", "libx264",
                            "-preset", "ultrafast", source])
            self.assertEqual(made.returncode, 0, made.stderr)
            result = execute([sys.executable, RUN, "inspect", source, "--out", root / "index",
                              "--interval", ".25", "--max-frames", "5"])
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            manifest = json.loads((root / "index/manifest.json").read_text())
            entry = manifest["files"][0]
            self.assertEqual(len(entry["frames"]), 5)
            self.assertTrue(Path(entry["contact_sheet"]).is_file())
            self.assertTrue(all(0 <= row["timestamp_seconds"] < 1 for row in entry["frames"]))
            transcript = root / "transcript.json"
            result = execute([sys.executable, RUN, "transcribe", source, "--out", transcript,
                              "--model", root / "deliberately-absent-model"])
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(json.loads(transcript.read_text())["status"], "no_audio")
            cached = execute([sys.executable, RUN, "transcribe", source, "--out", transcript,
                              "--model", root / "deliberately-absent-model"])
            self.assertEqual(cached.returncode, 0, cached.stderr)
            self.assertTrue(json.loads(cached.stdout)["cached"])

    def test_portable_launcher_source_clock_and_decoded_cut(self):
        with tempfile.TemporaryDirectory(prefix="storytelling-render-test-") as tmp:
            root = Path(tmp)
            project = root / "project with spaces"
            outside = root / "outside"
            project.mkdir()
            outside.mkdir()
            source = project / "镜头 ' source.mp4"
            made = execute(["ffmpeg", "-v", "error", "-f", "lavfi", "-i",
                            "color=c=red:s=320x180:r=25:d=1", "-f", "lavfi", "-i",
                            "color=c=blue:s=320x180:r=25:d=1", "-filter_complex",
                            "[0:v][1:v]concat=n=2:v=1:a=0[v]", "-map", "[v]",
                            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", source])
            self.assertEqual(made.returncode, 0, made.stderr)
            plan = {"version": 1, "title": "Synthetic timing check",
                    "output": {"width": 320, "height": 180, "fps": 25, "fit": "contain"},
                    "clips": [{"source": source.name, "in": 1, "out": 1.8},
                              {"source": source.name, "in": .2, "out": .8}],
                    "captions": [{"clip": 1, "start": .3, "end": .6,
                                  "en": "[Test footage] Caption mapping"}]}
            path = project / "edit.json"
            path.write_text(json.dumps(plan), encoding="utf-8")
            result = execute([sys.executable, RUN, "render", path, "--out", project / "output"], outside)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            manifest = json.loads((project / "output/manifest.json").read_text())
            self.assertAlmostEqual(manifest["render_duration"], 1.4)
            self.assertAlmostEqual(manifest["captions"][0]["start"], .9)
            self.assertIn("00:00:00,900 --> 00:00:01,200", (project / "output/en.srt").read_text())
            for timestamp, dominant in ((.2, 2), (1.05, 0)):
                frame = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(timestamp), "-i",
                                        str(project / "output/master.mp4"), "-frames:v", "1", "-vf",
                                        "scale=1:1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                                       capture_output=True, check=True).stdout
                self.assertGreater(frame[dominant], 180)
                self.assertLess(frame[0 if dominant == 2 else 2], 50)
            probe = execute(["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0",
                             "-show_entries", "stream=nb_read_frames,width,height", "-of", "json",
                             project / "output/master.mp4"])
            stream = json.loads(probe.stdout)["streams"][0]
            self.assertEqual(int(stream["nb_read_frames"]), 35)
            self.assertEqual((stream["width"], stream["height"]), (320, 180))
            again = execute([sys.executable, RUN, "render", path, "--out", project / "output"], outside)
            self.assertNotEqual(again.returncode, 0)
            self.assertIn("refusing to overwrite", again.stderr)
            # Invalid source-clock captions must fail instead of drifting into another shot.
            plan["captions"][0]["end"] = .9
            path.write_text(json.dumps(plan))
            rejected = execute([sys.executable, RUN, "render", path, "--out", project / "bad"], outside)
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn("inside its source clip", rejected.stderr)

    def test_doctor_is_independent_of_working_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = execute([sys.executable, RUN, "doctor"], tmp)
            self.assertEqual(result.returncode, 0, result.stderr)
            data = json.loads(result.stdout)
            self.assertTrue(data["capabilities"]["render"])
            self.assertFalse(data["checks"]["local_asr_model"]["ok"])


if __name__ == "__main__":
    unittest.main()
