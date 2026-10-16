"""v2: 360 reprojection, camera moves, effects, transitions, SFX, fx planner, 剪映 mapping, x5 stitch."""
import shutil
import unittest

import autocut_support as S

S.require_autocut()  # 缺少 autocut 依赖时整个模块跳过

import math
import shutil
from pathlib import Path
import numpy as np
from vcut.edl import (CUSTOM_TRANSITIONS, EDL, FX, FX_TYPES, JIANYING_TRANSITION, MOVES_2D, MOVES_360, Clip, Freeze,
                      Move, Ramp, Transition)
from vcut.fx.camera2d import Camera2D, pulse_env
from vcut.fx.ease import EASINGS, Track, ease, smooth_series
from vcut.fx.effects import LAZY, REGISTRY, make_effect
from vcut.fx.moves360 import Shot360
from vcut.fx.sfx import KINDS, synth
from vcut.fx.sphere import Reprojector, View
from vcut.fx.transitions import Transitioner


def quadrant_equirect(w=720, h=360):
    """Longitude quadrants: yaw 0 (centre) red, +90 green, ±180 blue, -90 yellow (BGR)."""
    img = np.zeros((h, w, 3), np.uint8)
    lon = (np.arange(w) + 0.5) / w * 360 - 180
    cols = {0: (0, 0, 255), 90: (0, 255, 0), 180: (255, 0, 0), -90: (0, 255, 255)}
    for x, L in enumerate(lon):
        k = min(cols, key=lambda c: min(abs(L - c), 360 - abs(L - c)))
        img[:, x] = cols[k]
    return img


# ------------------------------------------------------------------ easing / tracks


# ------------------------------------------------------------------ 360 reprojection


# ------------------------------------------------------------------ camera 2D


# ------------------------------------------------------------------ effects / transitions / sfx


# ------------------------------------------------------------------ EDL v2 timing


# ------------------------------------------------------------------ planner


def _plan_project(tmp_path, style_id):
    from vcut import config
    from vcut.plan.fxplan import plan_fx, plan_structure
    from vcut.project import Project

    p = Project.create(f"fx_{style_id}", "event", parent=tmp_path)
    p.save_media([{"id": "eq", "path": "eq.mp4", "source_name": "eq.mp4", "kind": "video", "projection": "equirect"},
                  {"id": "fa", "path": "fa.mp4", "source_name": "fa.mp4", "kind": "video", "projection": "flat"},
                  {"id": "th", "path": "th.mp4", "source_name": "th.mp4", "kind": "video", "projection": "flat"}])
    cat = [
        {"uid": "eq#0", "media_id": "eq", "path": "eq.mp4", "start": 0, "end": 8, "duration": 8, "category": "establishing",
         "activity": 0.02, "peak_t": 3.0, "projection": "equirect", "highlight": 0.7},
        {"uid": "fa#0", "media_id": "fa", "path": "fa.mp4", "start": 0, "end": 10, "duration": 10, "category": "action",
         "activity": 0.09, "peak_t": 5.0, "projection": "flat", "highlight": 0.8},
        {"uid": "th#0", "media_id": "th", "path": "th.mp4", "start": 0, "end": 10, "duration": 10, "category": "talking_head",
         "activity": 0.01, "peak_t": 5.0, "projection": "flat", "highlight": 0.5},
    ]
    clips = [Clip(id="c001", media_id="eq", src="eq.mp4", **{"in": 0.0}, out=4.0, role="establishing", section="hook"),
             Clip(id="c002", media_id="fa", src="fa.mp4", **{"in": 0.0}, out=3.0, role="action", section="hook"),
             Clip(id="c003", media_id="fa", src="fa.mp4", **{"in": 3.0}, out=8.0, role="action", section="content"),
             Clip(id="c004", media_id="th", src="th.mp4", **{"in": 0.0}, out=6.0, role="talking_head", section="people"),
             Clip(id="c005", media_id="eq", src="eq.mp4", **{"in": 4.0}, out=8.0, role="establishing", section="outro"),
             Clip(id="c006", media_id="eq", src="eq.mp4", **{"in": 0.5}, out=3.5, role="crowd", section="outro")]
    edl = EDL(clips=clips)
    style = config.get_style(style_id)
    marks = [("hook", 0, 1), ("content", 2, 2), ("people", 3, 3), ("outro", 4, 5)]
    plan_structure(edl, p, style, cat)
    edl.normalize_transitions()
    total = edl.total_duration
    track = {"beats": [round(0.5 * k, 3) for k in range(1, int(total * 2))], "duration": 120}
    notes = plan_fx(edl, p, style, cat, marks, [{"id": m[0], "name": m[0]} for m in marks], track, do_track=False)
    return edl, notes


# ------------------------------------------------------------------ 剪映 mapping


# ------------------------------------------------------------------ ffmpeg-backed (slow)


class AutocutFxTests(unittest.TestCase):
    tmp_path = S.tmp_path_factory
    monkeypatch = S.monkeypatch_factory

    def test_easings_endpoints_and_track(self):
        for name in EASINGS:
            assert abs(ease(name, 0.0)) < 1e-6 and abs(ease(name, 1.0) - 1.0) < 1e-6, name
        tr = Track([(0, 0.0), (2, 10.0)], "linear")
        assert abs(tr(1.0) - 5.0) < 1e-6 and tr(-1) == 0.0 and tr(9) == 10.0
        ys = smooth_series([0, 10, 0, 10, 0], [0, 0.5, 1, 1.5, 2], sigma_s=0.5)
        assert max(ys) < 10  # smoothed

    def test_reprojector_yaw_heading(self):
        for case in [(0, (0, 0, 255)), (90, (0, 255, 0)), (180, (255, 0, 0)), (-90, (0, 255, 255))]:
            with self.subTest(case=case):
                self._test_reprojector_yaw_heading(*(case if isinstance(case, tuple) and len(['yaw', 'bgr'])>1 else (case,)))

    def _test_reprojector_yaw_heading(self, yaw, bgr):
        eq = quadrant_equirect()
        R = Reprojector(320, 180, eq.shape[1], eq.shape[0])
        out = R.render(eq, View(yaw, 0, 0, 60))
        assert out.shape == (180, 320, 3)
        assert tuple(int(v) for v in out[90, 160]) == bgr

    def test_reprojector_portrait_and_tiny_planet(self):
        eq = quadrant_equirect()
        R = Reprojector(180, 320, eq.shape[1], eq.shape[0])
        assert R.render(eq, View(0, 0, 0, 90)).shape == (320, 180, 3)
        planet = Reprojector(200, 200, eq.shape[1], eq.shape[0]).render(eq, View(0, -90, 0, 260, 1.0))
        # stereographic down-view: all four quadrant colours appear around the centre
        seen = {tuple(int(v) for v in planet[y, x]) for y in range(0, 200, 10) for x in range(0, 200, 10)}
        assert {(0, 0, 255), (0, 255, 0), (255, 0, 0), (0, 255, 255)} <= seen

    def test_moves360_shapes(self):
        for m in MOVES_360:
            s = Shot360(m, {}, 4.0, yaw_track=[[0, 30, -5], [4, 60, -5]])
            v0, v1 = s.view(0.0), s.view(4.0)
            assert isinstance(v0, View) and isinstance(v1, View)
        pi = Shot360("planet_intro", {}, 4.0)
        assert pi.view(0.0).d > 0.5 and pi.view(4.0).d < 0.2       # planet → normal
        orb = Shot360("orbit", {"turns": 1.0}, 4.0)
        assert abs((orb.view(4.0).yaw - orb.view(0.0).yaw) - 360) < 1
        fol = Shot360("follow", {}, 4.0, yaw_track=[[0, 10, -3], [4, 50, -3]])
        assert abs(fol.view(2.0).yaw - 30) < 1

    def test_camera2d_moves_and_punch(self):
        c = Camera2D("push_in", {"amount": 0.2}, 2.0, 640, 360, 960, 540)
        assert c.state(2.0).zoom > c.state(0.0).zoom
        r = Camera2D("roll", {"degrees": 6}, 2.0, 640, 360, 960, 540)
        st = r.state(2.0)
        th = math.radians(6)
        assert st.zoom >= math.cos(th) + 16 / 9 * math.sin(th)   # rotated corners covered
        assert pulse_env(1.0, [1.0]) > 0.8 and pulse_env(1.5, [1.0]) < 0.2
        p = Camera2D("none", {}, 2.0, 640, 360, 960, 540, beats=[1.0], punch=0.15)
        assert p.state(1.03).zoom > 1.1 and p.state(0.5).zoom < 1.01

    def test_all_effects_run_and_change_image(self):
        rng = np.random.default_rng(0)
        img = (rng.random((180, 320, 3)) * 200 + 20).astype(np.uint8)
        img[60:120, 120:200] = 250  # a highlight for glow/bloom
        for name in REGISTRY:
            e = make_effect(name, 320, 180, 30, 1.0, {}, 1)
            out = fr = None
            for k in range(3):  # moving content so trail/motion-blur effects have something to smear
                fr = np.ascontiguousarray(np.roll(img, 12 * k, axis=1))
                out = e(fr, k / 30, 1.0)
            assert out.shape == img.shape and out.dtype == np.uint8, name
            assert np.abs(out.astype(int) - fr).mean() > 0.5, f"{name} had no visible effect"
        assert set(FX_TYPES) - set(REGISTRY) <= ({"punch", "shake"} | set(LAZY))   # camera fx handled by the engine

    def test_custom_transitions_endpoints(self):
        a = np.full((90, 160, 3), 40, np.uint8)
        b = np.full((90, 160, 3), 200, np.uint8)
        for kind in CUSTOM_TRANSITIONS:
            tr = Transitioner(kind, 160, 90, 30)
            f0, f1 = tr.frame(a, b, 0.0, 0.0), tr.frame(a, b, 1.0, 0.4)
            assert f0.shape == a.shape
            assert abs(float(f0.mean()) - 40) < 30 and abs(float(f1.mean()) - 200) < 30, kind

    def test_sfx_synth_kinds(self):
        for k in KINDS:
            s = synth(k)
            assert s.ndim == 2 and s.shape[0] == 2 and s.shape[1] > 4000 and np.abs(s).max() > 0.05, k

    def test_ramp_freeze_timing(self):
        c = Clip(id="a", media_id="m", src="x.mp4", **{"in": 10.0}, out=13.0,
                 ramp=Ramp(profile=[[0, 1], [0.4, 0.3], [0.7, 0.3], [1, 2]]), freeze=Freeze(at=1.0, hold=1.0))
        assert c.duration > c.base_duration
        ts = [c.out_to_src(t) for t in np.linspace(0, c.duration, 60)]
        assert all(b >= a - 1e-9 for a, b in zip(ts, ts[1:]))               # monotonic
        assert abs(ts[0] - 10.0) < 1e-6 and abs(ts[-1] - 13.0) < 1e-3
        assert abs(c.out_to_src(1.2) - c.out_to_src(1.8)) < 1e-9            # held during the freeze
        assert "punch" in FX_TYPES and "whip_left" in JIANYING_TRANSITION
        e = EDL(clips=[c, c.model_copy(update={"id": "b", "transition_in": Transition(type="zoom_through", duration=0.4)})])
        e.normalize_transitions()
        assert e.clips[1].transition_in.type == "zoom_through" and e.clips[1].transition_in.duration == 0.4

    def test_fxplan_beat_max(self):
        tmp_path = self.tmp_path()
        edl, notes = _plan_project(tmp_path, "beat_max")
        eq = [c for c in edl.clips if c.projection == "equirect"]
        assert len(eq) == 3 and all(c.move and c.move.type in MOVES_360 for c in eq)
        assert edl.clips[0].move.type == "planet_intro"                         # hook opens with planet → normal
        assert edl.clips[5].transition_in.type in ("whip_left", "whip_right")   # 360 → 360 = whip-pan heading change
        assert any(f.type == "punch" for c in edl.clips if c.role == "action" for f in c.fx)
        assert edl.beats and edl.downbeats and edl.flashes
        tl = edl.timeline()
        s4, e4 = tl[3]
        assert not any(s4 <= t < e4 for t, _ in edl.flashes)                    # never flash over talking heads
        assert not edl.clips[3].fx                                              # no flashy fx on the talking head
        assert any(a.kind == "sfx" for a in edl.audio)
        assert edl.text_anims.get("title") == "stamp" and edl.jianying.get("transition")
        for c in edl.clips:
            assert c.move is None or c.move.type in (MOVES_360 if c.projection == "equirect" else MOVES_2D)
            assert all(f.type in FX_TYPES for f in c.fx)

    def test_fxplan_cinematic_360_is_calm(self):
        tmp_path = self.tmp_path()
        edl, _ = _plan_project(tmp_path, "cinematic_360")
        assert not edl.flashes
        assert not any(f.type == "punch" for c in edl.clips for f in c.fx)
        assert {l.type for l in edl.look} >= {"grain", "vignette"}

    def test_yaml_on_key_guard(self):
        from vcut.plan.fxplan import _at
        assert _at({True: "beats"}) == "beats" and _at({"at": "downbeats"}) == "downbeats" and _at({}) == "none"

    def test_llm_fx_sanitize(self):
        from vcut.plan.fxplan import llm_vocab, sanitize_llm_clip_fx
        c = Clip(id="a", media_id="m", src="x.mp4", **{"in": 0.0}, out=3.0, role="action")
        sanitize_llm_clip_fx(c, {"move": "orbit", "fx": ["glitch", {"type": "nope"}, {"type": "flare", "start": 99, "dur": 5,
                                                                                       "intensity": 7}], "ramp": True, "freeze": "看!"})
        assert c.move is None                                    # 360 move rejected on a flat clip
        assert [f.type for f in c.fx] == ["glitch", "flare"]
        assert c.fx[1].start <= c.duration and c.fx[1].intensity == 1.0
        assert c.ramp is not None and c.freeze and c.freeze.text == "看!"
        e = Clip(id="b", media_id="m", src="x.mp4", **{"in": 0.0}, out=3.0, projection="equirect")
        sanitize_llm_clip_fx(e, {"move": {"type": "orbit", "params": {"turns": 1}}})
        assert e.move.type == "orbit"
        assert "planet_intro" in llm_vocab()

    def test_jianying_names_exist(self):
        S.importorskip("pyJianYingDraft")
        import pyJianYingDraft as jy

        from vcut import config
        from vcut.export.jianying_fx import SCENE_FX, TEXT_ANIM
        for name in set(SCENE_FX.values()):
            assert name in jy.VideoSceneEffectType.__members__, name
        for tin, tout, tloop in TEXT_ANIM.values():
            assert tin in jy.TextIntro.__members__ and tout in jy.TextOutro.__members__
            assert tloop is None or tloop in jy.TextLoopAnim.__members__
        for name in set(JIANYING_TRANSITION.values()):
            assert name in jy.TransitionType.__members__, name
            assert not jy.TransitionType.__members__[name].value.is_vip, f"{name} is VIP"
        enums = {"filter": jy.FilterType, "intro": jy.IntroType, "outro": jy.OutroType, "text_intro": jy.TextIntro,
                 "text_outro": jy.TextOutro, "text_loop": jy.TextLoopAnim, "transition": jy.TransitionType}
        for sid, st in config.styles().items():
            j = st.get("jianying") or {}
            for k, e in enums.items():
                if j.get(k):
                    assert j[k] in e.__members__, (sid, k, j[k])
            for n in (j.get("scene_effects") or {}).values():
                assert n in jy.VideoSceneEffectType.__members__, (sid, n)

    def test_jianying_keyframes_for_moves(self):
        S.importorskip("pyJianYingDraft")
        from vcut.export.jianying_fx import move_keyframes
        c = Clip(id="a", media_id="m", src="x.mp4", **{"in": 0.0}, out=3.0, move=Move(type="push_in", params={"amount": 0.2}))
        kf = move_keyframes(c, 3.0, [], 1920, 1080, 16 / 9)
        assert ("uniform_scale", 0.0, 1.0) in kf and any(p == "uniform_scale" and v > 1.15 for p, _, v in kf)
        c2 = Clip(id="b", media_id="m", src="x.mp4", **{"in": 0.0}, out=3.0, fx=[FX(type="punch", intensity=1.0)])
        kf2 = move_keyframes(c2, 3.0, [1.0, 2.0], 1920, 1080, 16 / 9)
        assert sum(1 for p, _, v in kf2 if p == "uniform_scale" and v > 1.1) == 2
        c3 = Clip(id="c", media_id="m", src="x.mp4", **{"in": 0.0}, out=3.0, focus_x=0.8)
        kf3 = move_keyframes(c3, 3.0, [], 1080, 1920, 16 / 9)   # 16:9 source on a 9:16 canvas → fill + pan to subject
        assert any(p == "uniform_scale" and v > 3 for p, _, v in kf3) and any(p == "position_x" and v < 0 for p, _, v in kf3)

    @unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg not installed")
    def test_x5_stitch_roundtrip(self):
        tmp_path = self.tmp_path()
        import cv2

        from vcut.media import ffmpeg
        from vcut.x360 import insv_layout, make_fake_insv, stitch_insv
        eq = tmp_path / "eq.mp4"
        img = quadrant_equirect(1024, 512)
        cv2.putText(img, "N", (500, 260), cv2.FONT_HERSHEY_SIMPLEX, 2, (255, 255, 255), 4)
        cv2.imwrite(str(tmp_path / "eq.png"), img)
        ffmpeg(["-loop", "1", "-i", str(tmp_path / "eq.png"), "-t", "1", "-r", "10", "-pix_fmt", "yuv420p", str(eq)])
        fake = make_fake_insv(eq, tmp_path / "VID_20260301_120000_00_001.insv", size=384, duration=1.0)
        assert insv_layout(fake)["layout"] == "two_track"
        r = stitch_insv(fake, tmp_path / "st.mp4", width=1024, preview=tmp_path / "p.jpg")
        back = cv2.imread(str(tmp_path / "p.jpg"))
        back = cv2.resize(back, (1024, 512))
        band = slice(150, 360)  # away from the poles (fisheye edge resolution)
        diff = np.abs(back[band].astype(int) - img[band].astype(int)).mean()
        assert diff < 25, diff
        assert Path(r["out"]).exists()

    @unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg not installed")
    def test_engine_renders_360_and_flat(self):
        tmp_path = self.tmp_path()
        import cv2

        from vcut.edl import PIP
        from vcut.fx.engine import render_clip
        from vcut.media import ffmpeg, probe
        from vcut.project import Project
        img = quadrant_equirect(1440, 720)
        cv2.imwrite(str(tmp_path / "eq.png"), img)
        eq = tmp_path / "eq.mp4"
        ffmpeg(["-loop", "1", "-i", str(tmp_path / "eq.png"), "-t", "2", "-r", "30", "-pix_fmt", "yuv420p", str(eq)])
        flat = tmp_path / "flat.mp4"
        ffmpeg(["-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30", "-t", "2", "-pix_fmt", "yuv420p", str(flat)])
        p = Project(tmp_path)
        c360 = Clip(id="a", media_id="e", src=str(eq), **{"in": 0.0}, out=1.5, projection="equirect", move=Move(type="planet_intro"))
        cflat = Clip(id="b", media_id="f", src=str(flat), **{"in": 0.0}, out=1.5, move=Move(type="push_in"),
                     fx=[FX(type="glitch", start=0.5, dur=0.5), FX(type="punch", params={"every": 1})],
                     freeze=Freeze(at=0.5, hold=0.5), pip=PIP(src=str(flat), layout="pip_br"))
        edl = EDL(width=320, height=180, fps=30, clips=[c360, cflat], beats=[0.5, 1.0, 1.5])
        for c, start in ((c360, 0.0), (cflat, 1.5)):
            out = tmp_path / f"{c.id}.mp4"
            render_clip(p, edl, c, start, out, 320, 180, 30, quick=True, encoder="libx264", lut_name="", color_filter="", cwd=tmp_path)
            pi = probe(out)
            assert abs(float(pi.duration) - c.duration) < 0.15, (c.id, pi.duration, c.duration)

