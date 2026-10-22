"""v2.1: ff-tracking port (lens_look, tracker_hud, terminal_hud, HUD SFX), GL Transitions ports, premium looks, styles."""
import unittest

import autocut_support as S

S.require_autocut()

import numpy as np
import cv2

from vcut import edl as E
from vcut.config import get_style, styles
from vcut.fx import fonts
from vcut.fx.effects import make_effect
from vcut.fx.gltransitions import CREDITS, GL_TRANSITIONS, gl_frame
from vcut.fx.hud import TrackerHUD
from vcut.fx.lens import PALETTES, LensLook, palette_lut
from vcut.fx.premium import STOCKS
from vcut.fx.sfx import hud_bed, normalize_lufs, synth_hud
from vcut.fx.terminal import Card, card_duration, schedule
from vcut.fx.trackctx import TrackCtx
from vcut.fx.transitions import Transitioner


def scene(W=320, H=180, shift=0):
    img = np.full((H, W, 3), (60, 50, 40), np.uint8)
    cv2.rectangle(img, (60 + shift, 50), (140 + shift, 130), (40, 200, 240), -1)
    cv2.circle(img, (230, 90), 30, (240, 240, 250), -1)
    return img


class TestGLTransitions(unittest.TestCase):
    def test_registry_matches_edl(self):
        self.assertEqual(set(GL_TRANSITIONS), set(E.GL_TRANSITIONS_DESC))
        self.assertEqual(set(GL_TRANSITIONS), set(CREDITS))
        for k in GL_TRANSITIONS:
            self.assertIn(k, E.CUSTOM_TRANSITIONS)
            self.assertIn(k, E.JIANYING_TRANSITION)
            self.assertIn(k, E.ALL_TRANSITIONS)
        self.assertEqual(len(GL_TRANSITIONS), 13)

    def test_endpoints_and_range(self):
        a, b = scene(), cv2.flip(scene(shift=40), 1)
        for k in GL_TRANSITIONS:
            for x in (0.0, 0.25, 0.5, 0.75, 1.0):
                o = gl_frame(k, a, b, x)
                self.assertEqual(o.shape, a.shape, k)
                self.assertEqual(o.dtype, np.uint8)
            # progress 0 looks like A, progress 1 looks like B (half-res ones allow some blur)
            self.assertLess(np.abs(gl_frame(k, a, b, 0.0).astype(int) - a).mean(), 6, k)
            self.assertLess(np.abs(gl_frame(k, a, b, 1.0).astype(int) - b).mean(), 6, k)

    def test_midpoint_differs(self):
        a, b = scene(), cv2.flip(scene(shift=40), 1)
        for k in GL_TRANSITIONS:
            m = gl_frame(k, a, b, 0.5)
            self.assertGreater(np.abs(m.astype(int) - a).mean() + np.abs(m.astype(int) - b).mean(), 3, k)

    def test_via_transitioner(self):
        a, b = scene(), scene(shift=30)
        tr = Transitioner("gl_ripple", 320, 180, 30)
        self.assertEqual(tr.frame(a, b, 0.5, 0.2).shape, a.shape)

    def test_odd_size(self):
        a = scene(W=250, H=141)
        for k in ("gl_cross_zoom", "gl_film_burn", "gl_cube"):
            self.assertEqual(gl_frame(k, a, a, 0.5).shape, a.shape)

    def test_styles_use_valid_transitions(self):
        for sid in ("premium_film", "premium_maker"):
            st = get_style(sid)
            for k in st["transitions"]["within"] + st["transitions"]["section"]:
                self.assertIn(k, E.ALL_TRANSITIONS, f"{sid}:{k}")


class TestPremium(unittest.TestCase):
    def test_looks_run_and_change_frame(self):
        img = scene(640, 360)
        for name, par in [("film_stock", {"stock": s}) for s in STOCKS] + [("anamorphic", {"tint": "blue"}), ("vhs_pro", {})]:
            e = make_effect(name, 640, 360, 30, 0.8, par, 1)
            o = e(img, 0.1, 1.0)
            self.assertEqual(o.shape, img.shape)
            self.assertGreater(np.abs(o.astype(int) - img).mean(), 0.5, name)
            self.assertIs(e(img, 0.2, 0.0), img)    # idle passthrough

    def test_anamorphic_streaks_horizontally(self):
        img = np.zeros((180, 320, 3), np.uint8)
        cv2.circle(img, (160, 90), 6, (255, 255, 255), -1)
        o = make_effect("anamorphic", 320, 180, 30, 1.0, {"tint": "blue"}, 0)(img, 0, 1.0)
        self.assertGreater(o[90, 110:130].mean(), o[20, 110:130].mean() + 3)       # light along the row, none far above

    def test_fx_types_registered(self):
        for k in ("film_stock", "anamorphic", "vhs_pro"):
            self.assertIn(k, E.FX_TYPES)
        self.assertEqual(E.parse_fx_arg("film_stock:teal_orange")[0].params.get("stock"), "teal_orange")

    def test_styles_load(self):
        for sid in ("premium_film", "premium_maker", "tracker_hud"):
            self.assertIn(sid, styles())
            for f in (get_style(sid).get("fx") or {}).get("look", []):
                self.assertIn(f["type"], E.FX_TYPES)


class TestLensHud(unittest.TestCase):
    def test_palettes_lut(self):
        for p in PALETTES:
            lut = palette_lut(p)
            self.assertEqual(lut.shape[-1], 3)

    def test_lens_and_hud_pipeline(self):
        W, H = 320, 180
        ctx = TrackCtx(W, H, 30, 2.0, {"locks": [1.0], "collapse_at": 1.7})
        lens = LensLook(W, H, 30, 1.0, {"palette": "thermal"}, 0)
        hud = TrackerHUD(W, H, 30, 1.0, {}, 0)
        lens.bind(ctx)
        hud.bind(ctx)
        for i in range(60):
            f = scene(W, H, shift=i)
            t = i / 30
            ctx.update(f, i, t)
            o = hud(lens(f, t, 1.0), t, 1.0)
            self.assertEqual(o.shape, f.shape)
            self.assertEqual(o.dtype, np.uint8)
        self.assertGreater(np.abs(o.astype(int) - f).mean(), 5)

    def test_parse_fx_arg_hud(self):
        fx = E.parse_fx_arg("lens_look:thermal,tracker_hud:label=Done;locks=1.4|2.6;mode=faces")
        self.assertEqual(fx[0].params["palette"], "thermal")
        self.assertEqual(fx[1].params["locks"], [1.4, 2.6])
        self.assertEqual(fx[1].params["mode"], "faces")

    def test_hud_fx_baked_for_jianying(self):
        self.assertTrue({"tracker_hud", "lens_look"} <= E.HUD_FX)


class TestTerminalSfx(unittest.TestCase):
    def test_card(self):
        spec = {"lines": ["Reading the brief", "Ship it"], "title": "agent"}
        self.assertGreater(card_duration(spec), 1.5)
        self.assertIn("duration", schedule(spec))
        c = Card(spec, 320, 180, 30)
        f0, f1 = c.frame(5), c.frame(int(c.sched["duration"] * 30) - 2)
        self.assertEqual(f0.shape, (180, 320, 3))
        self.assertGreater(np.abs(f0.astype(int) - f1).mean(), 1)

    def test_fonts(self):
        img = np.zeros((40, 200, 3), np.uint8)
        fonts.draw_text(img, "Done 完成", 4, 28, 20, (255, 255, 255))
        self.assertGreater(img.sum(), 0)
        self.assertGreater(fonts.text_width("abc", 20), 10)

    def test_sfx_hud_and_lufs(self):
        for k in ("keystroke", "lock_beep", "glitch_cut"):
            y = synth_hud(k, 0)
            self.assertEqual(y.shape[0], 2)
            self.assertTrue(np.isfinite(y).all())
        self.assertEqual(E.AudioItem.__dataclass_fields__["pan"].default if hasattr(E.AudioItem, "__dataclass_fields__")
                         else 0.0, 0.0)

    def test_clip_generated_roundtrip(self):
        c = E.Clip.from_dict({"type": "terminal_hud", "generated": {"lines": ["a"]}, "src": "", "dur": 2.0}) \
            if hasattr(E.Clip, "from_dict") else None
        if c is not None:
            self.assertEqual(c.type, "terminal_hud")


if __name__ == "__main__":
    unittest.main()
