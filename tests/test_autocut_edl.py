import shutil
import unittest

import autocut_support as S

S.require_autocut()  # 缺少 autocut 依赖时整个模块跳过

from vcut.edl import EDL, Clip, Transition
from vcut.plan.common import clean_sub_text, fill, split_cue


def mk(i, a, b, t="cut", d=0.0, speed=1.0, effects=None):
    return Clip(id=f"c{i}", media_id="m", src="x.mp4", **{"in": a}, out=b, speed=speed, effects=effects or [],
                transition_in=Transition(type=t, duration=d))


class AutocutEdlTests(unittest.TestCase):
    tmp_path = S.tmp_path_factory
    monkeypatch = S.monkeypatch_factory

    def test_timeline_with_transitions_and_speed(self):
        e = EDL(clips=[mk(1, 0, 4), mk(2, 0, 4, "fade", 1.0), mk(3, 0, 4, speed=2.0)])
        e.normalize_transitions()
        tl = e.timeline()
        assert tl[0] == (0.0, 4.0)
        assert tl[1] == (3.0, 7.0)          # 1s overlap
        assert tl[2] == (7.0, 9.0)          # 2x speed -> 2s
        assert e.total_duration == S.approx(9.0)

    def test_transition_clamped_and_first_is_cut(self):
        e = EDL(clips=[mk(1, 0, 1, "fade", 0.5), mk(2, 0, 1, "fade", 2.0), mk(3, 0, 0.1, "fade", 0.5)])
        e.normalize_transitions()
        assert e.clips[0].transition_in.type == "cut"
        assert e.clips[1].transition_in.duration <= 0.45 + 1e-9
        assert e.clips[2].transition_in.type == "cut"   # too short for any overlap

    def test_speed_ramp_duration_and_mapping(self):
        c = mk(1, 10, 20, effects=["speed_ramp"])
        # 6s at 1x + 4s at 2.5x = 6 + 1.6
        assert c.duration == S.approx(7.6)
        assert c.src_to_timeline(16, 0) == S.approx(6.0)
        assert c.src_to_timeline(20, 0) == S.approx(7.6)

    def test_unknown_transition_becomes_fade(self):
        assert Transition(type="spin3000", duration=0.3).type == "fade"

    def test_roundtrip(self):
        tmp_path = self.tmp_path()
        e = EDL(clips=[mk(1, 1.5, 3)], title="t")
        p = tmp_path / "edl.json"
        e.save(p)
        assert '"in": 1.5' in p.read_text(encoding="utf-8")
        assert EDL.load(p).clips[0].in_ == 1.5

    def test_split_cue_chinese_and_english(self):
        cues = split_cue("今天给大家看一下我做的智能台灯，它可以根据环境光自动调节亮度。", 0, 6, 14)
        assert all(len(c.text) <= 14 for c in cues)
        assert cues[0].start == 0 and cues[-1].end == S.approx(6)
        assert not cues[-1].text.endswith("。")
        assert split_cue("", 0, 1, 10) == []

    def test_fill_template(self):
        v = {"event_name": "", "event_location": "深圳", "title": "T"}
        assert fill("{event_name} · {event_location}", v) == "深圳"
        assert fill("{title}", v) == "T"
        assert clean_sub_text("你好，世界。") == "你好 世界"

