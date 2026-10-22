"""autocut ↔ toolkit 桥接：edit.json 往返、inspect 索引、转写、旁白，以及 `run autocut` 启动器。

只使用 FFmpeg 合成素材。
"""
import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

import autocut_support as S

S.require_autocut()

from vcut import bridge  # noqa: E402
from vcut.edl import EDL  # noqa: E402
from vcut.ingest import ingest  # noqa: E402
from vcut.plan import make_plan  # noqa: E402
from vcut.project import Project  # noqa: E402

RUN = S.ROOT / "skills/storytelling/video/run"
needs_ffmpeg = unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "ffmpeg not installed")


def execute(args, cwd=None, env=None):
    return subprocess.run([str(x) for x in args], cwd=cwd, capture_output=True, text=True, env=env)


class BridgePureTests(unittest.TestCase):
    tmp_path = S.tmp_path_factory

    def test_convert_transcript_drops_empty_and_keeps_language(self):
        data = {"status": "transcribed", "language": "zh", "model": "small", "segments": [
            {"start": 0.0, "end": 1.5, "text": " 大家好 ", "no_speech_prob": 0.01, "words": []},
            {"start": 2.0, "end": 2.0, "text": "零长度"}, {"start": 3.0, "end": 4.0, "text": "  "}]}
        out = bridge.convert_transcript(data)
        self.assertEqual([s["text"] for s in out["segments"]], ["大家好"])
        self.assertEqual(out["language"], "zh")
        self.assertIsNone(bridge.convert_transcript({"status": "no_audio", "segments": []}))

    def test_parse_srt(self):
        cues = bridge.parse_srt("1\n00:00:01,000 --> 00:00:02,500\n你好\n\n2\n00:01:00,000 --> 00:01:01,000\nHello\nworld\n")
        self.assertEqual(cues, [(1.0, 2.5, "你好"), (60.0, 61.0, "Hello world")])

    def test_toolkit_dir_found_inside_skill(self):
        self.assertEqual(bridge.toolkit_video_dir(), S.ROOT / "skills/storytelling/video")


class BridgeMediaTests(unittest.TestCase):
    tmp_path = S.tmp_path_factory

    def _project(self, kind="vlog"):
        return Project.create("桥接测试", kind, parent=self.tmp_path())

    @needs_ffmpeg
    def test_export_edit_runs_in_toolkit_render(self):
        p = S.analyzed_project()
        edl = make_plan(p, "none", save=False)
        out_dir = self.tmp_path()
        plan, warns = bridge.export_edit(p, edl, out_dir / "edit.json")
        self.assertEqual(plan["version"], 1)
        self.assertEqual(len(plan["clips"]), len(edl.clips))
        self.assertTrue(plan["output"]["width"] % 2 == 0 and plan["output"]["height"] % 2 == 0)
        self.assertTrue(warns, "有损导出必须给出警告")
        res = execute([sys.executable, RUN, "render", out_dir / "edit.json", "--out", out_dir / "out", "--preview"])
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertTrue((out_dir / "out" / "master.mp4").is_file())

    @needs_ffmpeg
    def test_import_edit_creates_edl_with_subtitles(self):
        proj = self._project()
        media = S.media_dir()
        src = next(media.rglob("PRO_VID_20260301_101500_00_001.mp4"))
        work = self.tmp_path()
        (work / "edit.json").write_text(json.dumps({
            "version": 1, "title": "t", "output": {"width": 1280, "height": 720, "fps": 30, "fit": "cover"},
            "clips": [{"source": str(src), "in": 0.5, "out": 2.5, "reason": "开场"},
                      {"source": str(src), "in": 4.0, "out": 6.0}],
            "captions": [{"clip": 1, "start": 4.5, "end": 5.5, "zh": "第二段字幕"}]}), encoding="utf-8")
        edl, _ = bridge.import_edit(proj, work / "edit.json")
        self.assertEqual(len(edl.clips), 2)
        self.assertEqual((edl.width, edl.height), (1280, 720))
        cue = edl.subtitles[0]
        self.assertAlmostEqual(cue.start, 2.0 + 0.5, places=2)   # 第一段 2s + 第二段内偏移 0.5s
        path = bridge.save_edl(proj, edl)
        self.assertEqual(len(EDL.load(path).clips), 2)
        # 第二次保存会把旧方案放进 edl_history
        bridge.save_edl(proj, edl)
        self.assertTrue(list((proj.root / "analysis" / "edl_history").glob("edl_*.json")))

    @needs_ffmpeg
    def test_import_index_and_transcript_reuse(self):
        proj = self._project()
        src = next(S.media_dir().rglob("VID20260301103000.mp4"))
        manifest = self.tmp_path() / "manifest.json"
        manifest.write_text(json.dumps({"files": [{"id": "media_0001", "source": str(src), "name": src.name}]}), encoding="utf-8")
        bridge.import_index(proj, manifest)
        self.assertEqual([m["source_name"] for m in proj.media()], [src.name])
        tr = self.tmp_path() / "transcript.json"
        tr.write_text(json.dumps({"status": "transcribed", "language": "en", "model": "x",
                                  "segments": [{"start": 0.2, "end": 3.0, "text": "Hello there"}]}), encoding="utf-8")
        bridge.import_transcript(proj, src.name, tr)
        from vcut.analyze import analyze_project
        analyze_project(proj, do_asr=True)   # 没装 ASR 也应使用导入的转写
        m = proj.media()[0]
        data = json.loads((proj.analysis_dir / f"{m['id']}.json").read_text(encoding="utf-8"))
        self.assertEqual(data["transcript"]["segments"][0]["text"], "Hello there")
        self.assertTrue(any(s["speech"] for s in data["shots"]))

    @needs_ffmpeg
    def test_import_narration_adds_voiceover_and_ducking(self):
        p = S.analyzed_project()
        edl = make_plan(p, "none", save=False)
        d = self.tmp_path()
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=f=220:d=3", str(d / "narration.wav")], check=True)
        (d / "zh.srt").write_text("1\n00:00:00,000 --> 00:00:02,000\n这是旁白\n", encoding="utf-8")
        (d / "en.srt").write_text("", encoding="utf-8")
        bridge.import_narration(p, edl, d)
        self.assertTrue(any(a.kind == "voiceover" for a in edl.audio))
        self.assertEqual(edl.subtitles[0].text, "这是旁白")
        self.assertTrue(all(a.duck for a in edl.audio if a.kind == "music"))


class LauncherTests(unittest.TestCase):
    tmp_path = S.tmp_path_factory

    def test_run_autocut_help_and_styles(self):
        res = execute([sys.executable, RUN, "autocut", "--help"], cwd=self.tmp_path())
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("export-edit", res.stdout)
        res = execute([sys.executable, RUN, "autocut", "styles"], cwd=self.tmp_path())
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("beat_max", res.stdout)

    @needs_ffmpeg
    def test_doctor_reports_autocut_capability(self):
        res = execute([sys.executable, RUN, "doctor", "--require", "autocut"], cwd=self.tmp_path())
        report = json.loads(res.stdout)
        self.assertIn("autocut", report["capabilities"])
        self.assertTrue(report["checks"]["autocut_core"]["ok"])
        self.assertIn("pyJianYingDraft", report["checks"]["autocut_optional"])

    def test_installed_copy_is_self_contained(self):
        target = self.tmp_path() / "skills"
        res = execute([sys.executable, S.ROOT / "scripts/install_skill.py", "--target", target])
        self.assertEqual(res.returncode, 0, res.stderr)
        run = target / "storytelling/video/run"
        res = execute([sys.executable, run, "autocut", "devices"], cwd=self.tmp_path())
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("rayban_meta", res.stdout + res.stderr)
        self.assertFalse(list(target.rglob("*.mp4")))


if __name__ == "__main__":
    unittest.main()
