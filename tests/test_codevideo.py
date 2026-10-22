"""Code-video ports: lyric timing, style index, title-card looks, character poses."""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
CODEVIDEO = ROOT / "skills/storytelling/codevideo"
sys.path.insert(0, str(CODEVIDEO))

import catalog  # noqa: E402
import karaoke  # noqa: E402
import looks  # noqa: E402
import lyrics  # noqa: E402
import styles  # noqa: E402


class LyricTests(unittest.TestCase):
    def setUp(self):
        self.payload = json.loads((CODEVIDEO / "examples/lyrics.json").read_text(encoding="utf-8"))
        self.lyrics = lyrics.Lyrics(self.payload)

    def test_queries_and_syllable_wipe(self):
        self.assertIsNone(self.lyrics.word_at(1.0))
        self.assertEqual(self.lyrics.line_at(1.0).i, 0)
        self.assertIsNone(self.lyrics.line_at(2.7))
        self.assertEqual(self.lyrics.line_at(3.2).text, "灯亮了，故事才开始")
        question = self.lyrics.find_words("question")[0]
        self.assertAlmostEqual(lyrics.Lyrics.word_progress(question, 2.13), 0.25)
        self.assertEqual(lyrics.Lyrics.word_progress(question, 0), 0)
        self.assertEqual(lyrics.Lyrics.word_progress(question, 9), 1)
        self.assertEqual(self.lyrics.get("question").i, 0)
        with self.assertRaises(lyrics.LyricError):
            self.lyrics.get("missing line")

    def test_smart_quotes_and_ass(self):
        self.assertEqual(lyrics.smart("don't"), "don’t")
        self.assertEqual(lyrics.smart("'cause"), "’cause")
        self.assertEqual(lyrics.smart('"Hello"'), "“Hello”")
        self.assertEqual(lyrics.plain(lyrics.smart("wait...")), "wait...")
        text = lyrics.to_ass(self.lyrics, 1280, 720)
        self.assertIn("{\\k22}The", text)
        self.assertIn("{\\k74}question", text)
        self.assertIn("灯亮了，", text)
        self.assertIn("PlayResX: 1280", text)

    def test_export_and_ffmpeg_ass(self):
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            self.skipTest("ffmpeg is not installed")
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "lyrics"
            manifest = karaoke.export(self.payload, output, 320, 180)
            self.assertEqual(manifest["line_count"], 2)
            self.assertTrue((output / "lyrics.ass").is_file())
            subprocess.run(
                [ffmpeg, "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=black:s=320x180:d=1",
                 "-vf", "ass=filename=lyrics.ass", "-f", "null", "-"],
                cwd=output, check=True,
            )


class StyleAndCatalogTests(unittest.TestCase):
    def test_style_search(self):
        lemo = styles.lemo_styles()
        mg = styles.mg_styles()
        self.assertEqual(len(lemo), 51)
        self.assertEqual(len(mg), 15)
        self.assertTrue(all(row["folder"] != "my-style" for row in lemo))
        ink = styles.find("水墨")
        self.assertTrue(any(row["folder"] == "ink-wash" for row in ink))
        bauhaus = styles.find("bauhaus")
        self.assertTrue(any(row["kind"] == "mg" and "09-bauhaus" in row["folder"] for row in bauhaus))
        for row in lemo + mg:
            self.assertTrue((ROOT / "skills/storytelling" / row["path"]).is_file())
            self.assertFalse(row["path"].startswith("/"))

    def test_opus_index_has_no_prompt_bodies(self):
        payload = catalog.load()
        self.assertEqual(payload["counts"]["motion"], 369)
        self.assertEqual(payload["counts"]["explainer"], 116)
        self.assertEqual(len(payload["entries"]), 703)
        self.assertLess((CODEVIDEO / "opus-index.json").stat().st_size, 512_000)
        rows = catalog.query(payload, category="explainer", tag="canvas", limit=5)
        self.assertEqual(len(rows), 5)
        self.assertTrue(all(row["category"] == "explainer" and "canvas" in row["tech_tags"] for row in rows))
        slug = catalog.query(payload, slug="ror-fly-880547", limit=5)
        self.assertEqual(slug[0]["prompt_url"].endswith("/prompts/ror-fly-880547.md"), True)
        self.assertNotIn("prompt", slug[0])


class LookTests(unittest.TestCase):
    def test_grade_and_particles_are_deterministic(self):
        image = Image.new("RGB", (40, 40), "black")
        for x in range(16, 24):
            for y in range(16, 24):
                image.putpixel((x, y), (255, 255, 255))
        first, second = looks.grain(image, 0.2, seed=4), looks.grain(image, 0.2, seed=4)
        self.assertEqual(first.tobytes(), second.tobytes())
        self.assertNotEqual(first.tobytes(), image.tobytes())
        glowed = looks.bloom(image, threshold=200, radius=2, strength=1)
        self.assertGreater(glowed.getpixel((26, 20))[0], 0)
        self.assertEqual(glowed.getpixel((0, 0)), (0, 0, 0))
        white = looks.vignette(Image.new("RGB", (21, 21), "white"), 0.45)
        self.assertEqual(white.getpixel((10, 10)), (255, 255, 255))
        self.assertLess(white.getpixel((0, 0))[0], 180)
        a = looks.particle_points(32, 24, 0.0, count=8, seed=2)
        b = looks.particle_points(32, 24, 0.0, count=8, seed=2)
        c = looks.particle_points(32, 24, 0.7, count=8, seed=2)
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)
        graded = looks.apply_looks(image, {"grain": 0.05, "bloom": {"radius": 1}, "vignette": 0.2,
                                            "particles": {"count": 4, "time": 0.2, "seed": 1}})
        self.assertEqual(graded.size, image.size)
        self.assertEqual(graded.mode, "RGB")


class CharacterTemplateTests(unittest.TestCase):
    def test_page_contract_and_pose_module(self):
        page = (ROOT / "skills/storytelling/templates/character-beat.html").read_text(encoding="utf-8")
        self.assertIn("window.renderFrame", page)
        self.assertIn("../codevideo/performance.js", page)
        script = ROOT / "tests/check_performance.mjs"
        subprocess.run(["node", "--check", str(CODEVIDEO / "performance.js")], check=True)
        subprocess.run(["node", str(script)], check=True)


if __name__ == "__main__":
    unittest.main()
