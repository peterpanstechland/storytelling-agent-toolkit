import shutil
import unittest

import autocut_support as S

S.require_autocut()  # 缺少 autocut 依赖时整个模块跳过

from pathlib import Path
from vcut import config
from vcut.devices import detect_device
from vcut.media import ProbeInfo


def _pi(tags=None):
    return ProbeInfo(path="x", kind="video", tags=tags or {})


DEVICE_CASES = [
    ("PRO_VID_20260301_101500_00_001.mp4", {}, "ace_pro_2"),
    ("VID_20260301_102000_00_002.mp4", {}, "go_ultra"),
    ("VID_20260301_105000_00_003.insv", {}, "x5"),
    ("VID20260301103000.mp4", {"com.android.manufacturer": "OnePlus", "com.android.model": "PJD110"}, "android_phone"),
    ("clip.mp4", {"com.android.manufacturer": "HONOR", "com.android.model": "XYZ-AN00"}, "honor_robot"),
    ("IMG_0001.MOV", {"com.apple.quicktime.model": "iPhone 16"}, "iphone"),
    ("random.mp4", {}, "unknown"),
]


class AutocutConfigDevicesTests(unittest.TestCase):
    tmp_path = S.tmp_path_factory
    monkeypatch = S.monkeypatch_factory

    def test_yaml_files_load(self):
        assert config.settings()["backend"] in ("none", "dashscope", "gemini", "ollama")
        assert {"tech_minimal", "energetic", "cinematic", "warm_daily"} <= set(config.styles())
        assert {"event", "sponsored", "maker", "vlog"} <= set(config.type_templates())

    def test_type_templates_consistent(self):
        for case in ['event', 'sponsored', 'maker', 'vlog']:
            with self.subTest(case=case):
                self._test_type_templates_consistent(*(case if isinstance(case, tuple) and len(['tid'])>1 else (case,)))

    def _test_type_templates_consistent(self, tid):
        t = config.get_type(tid)
        total = sum(float(s["ratio"]) for s in t["sections"])
        assert abs(total - 1.0) < 0.02, total
        sec_ids = {s["id"] for s in t["sections"]}
        for s in t["sections"]:
            assert set(s["categories"]) <= set(config.CATEGORIES), s
        for shot in t["shots"]:
            assert shot["section"] in sec_ids, shot
            assert shot["category"] in config.CATEGORIES, shot

    def test_style_aliases(self):
        assert config.get_style("科技感")["id"] == "tech_minimal"
        assert config.get_style("活力快剪")["id"] == "energetic"
        assert config.get_style("电影感")["id"] == "cinematic"
        with S.raises(KeyError):
            config.get_style("不存在的风格")

    def test_detect_device(self):
        for name, tags, expected in DEVICE_CASES:
            with self.subTest(name=name):
                assert detect_device(Path(name), _pi(tags))["id"] == expected

    def test_ray_ban_meta_by_comment_and_vertical_resolution(self):
        comment = {"comment": "device=Ray-Ban Meta Smart Glasses"}
        d = detect_device(Path("clip.mp4"), ProbeInfo(path="x", kind="video", width=1392, height=1872, tags=comment))
        assert d["id"] == "rayban_meta" and d["kind"] == "glasses"
        # 只有分辨率（没有元数据）不会被误判成眼镜
        assert detect_device(Path("clip.mp4"), ProbeInfo(path="x", kind="video", width=1392, height=1872))["id"] == "unknown"

    def test_default_devices_are_generic(self):
        text = (S.AUTOCUT / "config" / "devices.yaml").read_text(encoding="utf-8")
        ids = {d["id"] for d in config.devices()}
        assert {"x5", "ace_pro_2", "go_ultra", "rayban_meta", "iphone", "android_phone", "honor_robot"} <= ids
        assert "借用" not in text and "3080" not in text

    def test_device_list_is_config_driven(self):
        devs = [{"id": "cam", "label": "Cam", "kind": "action", "match": {"tags": ["MyCam"]}}]
        assert detect_device(Path("a.mp4"), _pi({"model": "MyCam 3"}), device_list=devs)["id"] == "cam"

