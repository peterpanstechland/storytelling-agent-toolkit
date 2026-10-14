"""Observable card-renderer behavior; no external assets or network required."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from PIL import Image

SCRIPT = Path(__file__).resolve().parents[1] / "skills/storytelling/scripts/render_cards.py"
spec = importlib.util.spec_from_file_location("story_cards", SCRIPT)
cards = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cards)


class CardRendererTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.spec = self.base / "cards.json"
        self.out = self.base / "rendered"
        try:
            self.font = str(cards.choose_font(None, "English"))
        except cards.CardError as exc:
            self.skipTest(str(exc))

    def tearDown(self):
        self.temp.cleanup()

    def write(self, items, **kwargs):
        data = {"version": 1, "title": "Test", "author": "Demo", "cards": items}
        data.update(kwargs)
        self.spec.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return self.spec

    def basic(self, **kwargs):
        item = {"id": "opening", "layout": "cover", "title": "A useful question", "body": "Evidence makes it clear."}
        item.update(kwargs)
        return item

    def test_five_layouts_and_mixed_dimensions(self):
        Image.new("RGB", (700, 400), "#c94251").save(self.base / "photo.png")
        self.write([
            self.basic(),
            self.basic(id="photo", layout="photo-overlay", image="photo.png", image_focus=[0, 1]),
            self.basic(id="stat", layout="stat", value="12 trials", meaning="Fictional test count, not a success rate.", source="Source: fictional example."),
            self.basic(id="quote", layout="quote", width=1200, height=1200, title="Show the relationship.", attribution="Original demo copy"),
            self.basic(id="steps", layout="process", nodes=[{"title": "Observe", "body": "Start with a question."}, {"title": "Explain", "body": "Interpret the evidence."}]),
        ])
        result = cards.export(self.spec, self.out, self.font)
        self.assertEqual(len(result["cards"]), 5)
        for record in result["cards"]:
            with Image.open(self.out / record["file"]) as image:
                self.assertEqual(image.size, (record["width"], record["height"]))
            for box in record["text_boxes"]:
                x, y, w, h = box["box"]
                self.assertGreaterEqual(x, 0)
                self.assertGreaterEqual(y, 0)
                self.assertLessEqual(x + w, record["width"] + 1)
                self.assertLessEqual(y + h, record["height"] + 1)
                self.assertLessEqual(box["used_height"], h)
        self.assertTrue((self.out / "index.html").is_file())
        self.assertEqual(result["cards"][3]["height"], 1200)

    def test_overflow_fails_without_partial_export(self):
        self.write([self.basic(), self.basic(id="too-long", title="Extremely long copy " * 140)])
        with self.assertRaisesRegex(cards.CardError, "overflows"):
            cards.export(self.spec, self.out, self.font)
        self.assertFalse(self.out.exists())

    def test_force_cannot_overwrite_unrelated_files(self):
        self.out.mkdir()
        untouched = self.out / "opening.png"
        untouched.write_bytes(b"not a generated file")
        self.write([self.basic()])
        with self.assertRaisesRegex(cards.CardError, "Refusing to overwrite"):
            cards.export(self.spec, self.out, self.font, force=True)
        self.assertEqual(untouched.read_bytes(), b"not a generated file")

    def test_rerender_changes_owned_files_and_retains_other_files(self):
        self.write([self.basic()])
        cards.export(self.spec, self.out, self.font)
        image = self.out / "opening.png"
        before = hashlib.sha256(image.read_bytes()).hexdigest()
        unrelated = self.out / "notes.txt"
        unrelated.write_text("Keep these notes", encoding="utf-8")
        self.write([self.basic(title="A revised question")])
        with self.assertRaises(cards.CardError):
            cards.export(self.spec, self.out, self.font)
        cards.export(self.spec, self.out, self.font, force=True)
        self.assertNotEqual(hashlib.sha256(image.read_bytes()).hexdigest(), before)
        self.assertEqual(unrelated.read_text(), "Keep these notes")

    def test_failed_revision_preserves_previous_render(self):
        self.write([self.basic()])
        cards.export(self.spec, self.out, self.font)
        before = {p.name: p.read_bytes() for p in self.out.iterdir()}
        self.write([self.basic(title="Long " * 500)])
        with self.assertRaises(cards.CardError):
            cards.export(self.spec, self.out, self.font, force=True)
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.out.iterdir()})

    def test_photo_paths_are_relative_and_confined(self):
        for path in ("/etc/passwd", "../outside.png", "https://example.com/photo.png"):
            with self.subTest(path=path):
                self.write([self.basic(layout="photo-overlay", image=path)])
                with self.assertRaises(cards.CardError):
                    cards.load_spec(self.spec)

    def test_invalid_numeric_values_and_duplicate_ids_rejected(self):
        for changes in ({"width": True}, {"height": 0}, {"width": 9000}, {"width": float("nan")}, {"width": 8192, "height": 8192}):
            with self.subTest(changes=changes):
                self.write([self.basic(**changes)])
                with self.assertRaises(cards.CardError):
                    cards.load_spec(self.spec)
        self.write([self.basic(), self.basic()])
        with self.assertRaises(cards.CardError):
            cards.load_spec(self.spec)

    def test_stat_requires_interpretation_and_source(self):
        self.write([self.basic(layout="stat", value="50%")])
        with self.assertRaisesRegex(cards.CardError, "meaning"):
            cards.load_spec(self.spec)
        self.write([self.basic(layout="stat", value="50%", meaning="An example only")])
        with self.assertRaisesRegex(cards.CardError, "source"):
            cards.load_spec(self.spec)

    def test_preview_escapes_user_text(self):
        self.write([self.basic(alt="<script>alert('x')</script>")], title="A < demo")
        cards.export(self.spec, self.out, self.font)
        output = (self.out / "index.html").read_text()
        self.assertNotIn("<script>", output)
        self.assertIn("&lt;script&gt;", output)
        self.assertIn("A &lt; demo", output)

    def test_font_validation_for_missing_cjk(self):
        latin = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
        if not latin.is_file():
            self.skipTest("Known Latin test font not installed")
        with self.assertRaisesRegex(cards.CardError, "CJK"):
            cards.choose_font(str(latin), "科技")

    def test_long_latin_token_wraps_within_measured_column(self):
        self.write([self.basic(title="Supercalifragilisticexpialidocious" * 2)])
        result = cards.export(self.spec, self.out, self.font)
        title = result["cards"][0]["text_boxes"][0]
        self.assertGreater(title["line_count"], 1)
        self.assertLessEqual(title["used_height"], title["box"][3])


if __name__ == "__main__":
    unittest.main()
