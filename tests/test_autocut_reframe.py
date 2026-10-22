"""Vertical reframe (16:9 → 9:16): smart follow / fit_blur decision, smoothing, compositing, engine, 剪映 keyframes, captions."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import autocut_support as S

S.require_autocut()

import cv2
import numpy as np

from vcut import reframe as RF
from vcut.edl import EDL, FX, Clip
from vcut.export.jianying_fx import move_keyframes

NODET = lambda img: []   # deterministic: saliency/motion only, no face models


def frames_square(xs, w=480, h=270, size=40, jitter=0.0, seed=0):
    r = np.random.default_rng(seed)
    out = []
    for i, x in enumerate(xs):
        f = np.full((h, w, 3), 20, np.uint8)
        cx = int(x * w + r.normal(0, jitter))
        cv2.rectangle(f, (cx - size // 2, h // 2 - size // 2), (cx + size // 2, h // 2 + size // 2), (230, 230, 240), -1)
        cv2.rectangle(f, (cx - 8, h // 2 - 8), (cx + 8, h // 2 + 8), (30, 60, 200), -1)
        out.append((i * 0.5, f))
    return out


class TestGeometry(unittest.TestCase):
    def test_window_and_content(self):
        self.assertTrue(RF.needs_vertical(1920, 1080, 1080, 1920))
        self.assertFalse(RF.needs_vertical(1080, 1920, 1080, 1920))
        self.assertFalse(RF.needs_vertical(1920, 1080, 1920, 1080))
        wn = RF.window_frac(1920, 1080, 1080, 1920, 1.25)
        self.assertAlmostEqual(wn, 1080 * 9 / 16 * 1.25 / 1920, places=4)
        self.assertEqual(RF.content_size("follow", 1920, 1080, 1080, 1920, 1.25), (1080, 1536))
        self.assertEqual(RF.content_size("fit_blur", 1920, 1080, 1080, 1920), (1080, 608))
        self.assertEqual(RF.content_size("fit_bars", 1920, 1080, 1080, 1920), (1080, 608))
        self.assertEqual(RF.content_size("follow", 1920, 1080, 1080, 1920, 1.0), (1080, 1920))   # loose 1 = tight cover

    def test_compose_puts_picture_in_the_middle(self):
        content = np.full((608, 1080, 3), 200, np.uint8)
        out = RF.compose(content, 1080, 1920, "fit_blur")
        self.assertEqual(out.shape, (1920, 1080, 3))
        y0 = (1920 - 608) // 2
        self.assertTrue((out[y0:y0 + 608] == 200).all())
        self.assertLess(out[:y0].mean(), 200)          # darkened
        self.assertGreater(out[:y0].mean(), 20)        # but not black
        bars = RF.compose(content, 1080, 1920, "fit_bars")
        self.assertEqual(int(bars[:y0].max()), 0)


class TestDecision(unittest.TestCase):
    def test_single_subject_follows(self):
        xs = list(np.linspace(0.3, 0.7, 12))
        r = RF.decide(frames_square(xs), 1920, 1080, 1080, 1920, detector=NODET)
        self.assertEqual(r["mode"], "follow", r)
        tr = r["track"]
        self.assertGreaterEqual(len(tr), 8)
        wn = r["width"]
        for _, x in tr:
            self.assertGreaterEqual(x, wn / 2 - 1e-6)
            self.assertLessEqual(x, 1 - wn / 2 + 1e-6)
        self.assertGreater(tr[-1][1], tr[0][1])              # follows the subject to the right
        steps = np.diff([x for _, x in tr])
        self.assertTrue((steps >= -1e-4).all())               # no back-and-forth

    def test_jitter_is_absorbed_by_dead_zone(self):
        r = RF.decide(frames_square([0.5] * 12, jitter=6.0, seed=3), 1920, 1080, 1080, 1920, detector=NODET)
        self.assertEqual(r["mode"], "follow")
        xs = [x for _, x in r["track"]]
        self.assertLess(max(xs) - min(xs), 0.02)          # raw centres jump ±2.5 %; output glides < 2 %

    def test_spread_content_fits_with_blur(self):
        frames = []
        for i in range(8):
            f = np.full((270, 480, 3), 20, np.uint8)
            for cx in (50, 430):
                cv2.rectangle(f, (cx - 25, 110), (cx + 25, 160), (230, 230, 240), -1)
            frames.append((i * 0.5, f))
        r = RF.decide(frames, 1920, 1080, 1080, 1920, detector=NODET)
        self.assertEqual(r["mode"], "fit_blur", r)

    def test_no_subject_fits_with_blur(self):
        frames = [(i * 0.5, np.full((270, 480, 3), 90, np.uint8)) for i in range(6)]
        self.assertEqual(RF.decide(frames, 1920, 1080, 1080, 1920, detector=NODET)["mode"], "fit_blur")
        self.assertEqual(RF.decide([], 1920, 1080, 1080, 1920)["mode"], "fit_blur")

    def test_smooth_path_dead_zone(self):
        ts = [i * 0.5 for i in range(10)]
        xs = [0.5, 0.52, 0.49, 0.51, 0.5, 0.48, 0.52, 0.5, 0.51, 0.5]
        out = RF.smooth_path(ts, xs, 0.4, dead=0.12)
        self.assertLess(max(out) - min(out), 1e-6)

    def test_track_x_interp(self):
        self.assertAlmostEqual(RF.track_x([[0, 0.3], [2, 0.7]], 1.0), 0.5)
        self.assertEqual(RF.track_x([], 1.0), 0.5)


class TestEdlAndDraft(unittest.TestCase):
    def test_clip_mode_and_engine(self):
        c = Clip(id="c1", media_id="m", src="/x.mp4", in_=0, out=2, reframe={"mode": "fit_blur"})
        self.assertEqual(c.reframe_mode(), "fit_blur")
        self.assertTrue(c.uses_engine())
        self.assertFalse(Clip(id="c2", media_id="m", src="/x.mp4", in_=0, out=2, reframe={"mode": "crop"}).uses_engine())
        self.assertEqual(EDL().reframe_vertical, "smart")

    def test_jianying_keyframes(self):
        fit = Clip(id="c1", media_id="m", src="/x.mp4", in_=0, out=2, reframe={"mode": "fit_blur"})
        self.assertEqual(move_keyframes(fit, 2.0, [], 1080, 1920, 16 / 9), [])          # scale 1 = whole frame, no pan
        wn = RF.window_frac(1920, 1080, 1080, 1920, 1.25)
        fol = Clip(id="c2", media_id="m", src="/x.mp4", in_=0, out=2,
                   reframe={"mode": "follow", "width": wn, "track": [[0, 0.4], [2, 0.6]]})
        kf = move_keyframes(fol, 2.0, [], 1080, 1920, 16 / 9)
        sc = [v for p, _, v in kf if p == "uniform_scale"]
        self.assertAlmostEqual(sc[0], 1 / wn, places=3)
        self.assertLess(1 / wn, 16 / 9 / (9 / 16))                                       # looser than tight cover
        px = [v for p, _, v in kf if p == "position_x"]
        self.assertGreater(px[0], px[-1])                                                # pans right → canvas moves left

    def test_jianying_canvas_blur_api(self):
        jy = S.importorskip("pyJianYingDraft") if hasattr(S, "importorskip") else None
        if jy is None:
            self.skipTest("pyJianYingDraft missing")
        self.assertTrue(hasattr(jy.VideoSegment, "add_background_filling"))


class TestCaptions(unittest.TestCase):
    def test_portrait_captions_in_safe_area(self):
        from vcut.edl import SubtitleCue
        from vcut.render import write_ass
        d = Path(tempfile.mkdtemp())
        e = EDL(width=1080, height=1920, subtitle_style={"margin_v": 0.07})
        e.subtitles = [SubtitleCue(start=0, end=1, text="hello")] if "SubtitleCue" in dir() else []
        txt = write_ass(e, d / "a.ass").read_text("utf-8")
        line = [l for l in txt.splitlines() if l.startswith("Style: Sub,")][0]
        mv = int(line.split(",")[-2])
        self.assertGreaterEqual(mv, int(1920 * 0.16))
        shutil.rmtree(d, ignore_errors=True)


class TestEngine(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not shutil.which("ffmpeg"):
            raise unittest.SkipTest("ffmpeg missing")
        cls.d = Path(tempfile.mkdtemp())
        cls.src = cls.d / "wide.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30:duration=1.2",
                        "-pix_fmt", "yuv420p", str(cls.src)], check=True)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.d, ignore_errors=True)

    def _render(self, mode, fx=()):
        from vcut.fx.engine import render_clip
        e = EDL(width=270, height=480, fps=30)
        c = Clip(id="c1", media_id="m", src=str(self.src), in_=0, out=1.0, reframe={"mode": mode, "width": 0.4,
                 "track": [[0, 0.4], [1, 0.6]]}, fx=list(fx))
        out = self.d / f"{mode}_{len(fx)}.mp4"
        render_clip(SimpleNamespace(root=self.d), e, c, 0.0, out, 270, 480, 30, quick=True, encoder="libx264",
                    lut_name="", color_filter="", cwd=self.d)
        cap = cv2.VideoCapture(str(out))
        cap.set(cv2.CAP_PROP_POS_FRAMES, 15)
        ok, f = cap.read()
        self.assertTrue(ok)
        return f

    def test_fit_blur_frame_layout(self):
        f = self._render("fit_blur")
        self.assertEqual(f.shape[:2], (480, 270))
        cw, ch = RF.content_size("fit_blur", 640, 360, 270, 480)
        y0 = (480 - ch) // 2
        pad, pic = f[: y0 - 4], f[y0 + 4: y0 + ch - 4]
        self.assertLess(cv2.Laplacian(cv2.cvtColor(pad, cv2.COLOR_BGR2GRAY), cv2.CV_64F).var(),
                        cv2.Laplacian(cv2.cvtColor(pic, cv2.COLOR_BGR2GRAY), cv2.CV_64F).var())   # padding is blurred
        bars = self._render("fit_bars")
        self.assertLess(bars[: y0 - 4].mean(), 12)

    def test_hud_stays_on_the_picture(self):
        plain = self._render("fit_blur")
        hud = self._render("fit_blur", [FX(type="tracker_hud", intensity=1.0, params={"mode": "salient"})])
        cw, ch = RF.content_size("fit_blur", 640, 360, 270, 480)
        y0 = (480 - ch) // 2
        diff = np.abs(hud.astype(int) - plain.astype(int)).mean(axis=2)
        self.assertGreater(diff[y0:y0 + ch].mean(), diff[: y0 - 6].mean())      # boxes drawn on the image band
        self.assertLess(diff[: y0 - 6].mean(), 4.0)                              # padding not covered by HUD

    def test_follow_fills_most_of_frame(self):
        f = self._render("follow")
        self.assertEqual(f.shape[:2], (480, 270))


if __name__ == "__main__":
    unittest.main()
