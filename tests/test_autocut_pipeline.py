"""End-to-end on synthetic footage (offline: heuristic planner, fake transcript, mocked LLM)."""
import shutil
import unittest

import autocut_support as S

S.require_autocut()  # 缺少 autocut 依赖时整个模块跳过

import json
import shutil
import xml.etree.ElementTree as ET
from vcut.analyze.catalog import build_catalog
from vcut.backends.base import Backend
from vcut.edl import EDL
from vcut.export import export_fcpxml, export_jianying, jianying_available
from vcut.gaps import find_gaps
from vcut.media import probe
from vcut.plan import make_plan
from vcut.plan.common import PlanError
from vcut.plan.heuristic import plan_heuristic
from vcut.plan.llm import edl_from_llm
from vcut.render import render
from vcut.shotlist import generate_shotlist


class FakeBackend(Backend):
    name = "fake"
    vision_model = "fake-vl"
    text_model = "fake-llm"

    def __init__(self, reply):
        self.reply = reply
        self.prompts = []

    def chat(self, prompt, *, system="", images=(), model=None, json_mode=True, temperature=0.3):
        self.prompts.append((prompt, len(images)))
        return self.reply(prompt) if callable(self.reply) else self.reply


def _no_reuse(edl: EDL):
    by_media = {}
    for c in edl.clips:
        for a, b in by_media.get(c.media_id, []):
            assert min(b, c.out) - max(a, c.in_) <= 0.3, f"footage reused: {c}"
        by_media.setdefault(c.media_id, []).append((c.in_, c.out))


class AutocutPipelineTests(unittest.TestCase):
    tmp_path = S.tmp_path_factory
    monkeypatch = S.monkeypatch_factory

    def test_ingest_and_analysis(self):
        analyzed_project = S.analyzed_project()
        p = analyzed_project
        media = p.media()
        names = {m["source_name"]: m for m in media}
        assert "VID_20260301_105000_00_003.insv" not in names           # raw 360 flagged, not ingested
        assert not any(n.endswith(".lrv") for n in names)
        assert names["PRO_VID_20260301_101500_00_001.mp4"]["device"]["id"] == "ace_pro_2"
        assert names["VID20260301103000.mp4"]["device"]["id"] == "android_phone"
        assert names["test_beat_120bpm.wav"]["role"] == "music"
        cat = build_catalog(p)
        ace = [u for u in cat if u["source_name"].startswith("PRO_VID")]
        assert [round(u["start"]) for u in ace] == [0, 4, 8]             # 3 synthetic scenes detected
        talk = [u for u in cat if u["source_name"] == "VID20260301103000.mp4"]
        assert all(u["category"] == "talking_head" for u in talk)
        assert all((p.root / k).exists() for u in cat for k in u["keyframes"])

    def test_analysis_is_incremental(self):
        analyzed_project = S.analyzed_project()
        from vcut.analyze import analyze_project
        import time

        t = time.time()
        analyze_project(analyzed_project, do_asr=False)
        assert time.time() - t < 5   # everything cached

    def test_shotlist_and_gaps(self):
        analyzed_project = S.analyzed_project()
        text, items = generate_shotlist(analyzed_project, backend_name="none")
        assert "拍摄清单" in text and "功能演示：自动调光" in text
        assert "Insta360 GO Ultra" in text                       # device recommendation from devices.yaml
        r = find_gaps(analyzed_project)
        by_id = {i["id"]: i for i in r["items"]}
        assert by_id["talk_intro"]["status"] in ("ok", "low")    # talking head present
        assert any(i["status"] == "missing" for i in r["items"])
        assert (analyzed_project.analysis_dir / "gaps.md").exists()

    def test_heuristic_plan(self):
        analyzed_project = S.analyzed_project()
        edl = plan_heuristic(analyzed_project)
        assert len(edl.clips) >= 5
        assert edl.planner == "heuristic"
        assert edl.clips[0].section == "hook"
        _no_reuse(edl)
        talk = [c for c in edl.clips if c.role == "talking_head"]
        assert talk and all(c.volume == 1.0 for c in talk)
        assert edl.subtitles and edl.subtitles[0].text
        assert any(o.kind == "title" for o in edl.overlays)
        assert any(a.kind == "music" for a in edl.audio)
        assert edl.total_duration <= 30 * 1.3

    def test_llm_plan_validation(self):
        analyzed_project = S.analyzed_project()
        from vcut.analyze.catalog import transcript_units

        p = analyzed_project
        cat = build_catalog(p)
        sents = transcript_units(p)
        data = {"title": "AI 片名", "clips": [
            {"ref": cat[0]["uid"], "in": cat[0]["start"], "out": cat[0]["start"] + 1.5, "section": "hook", "transition": "cut"},
            {"ref": sents[0]["uid"], "in": sents[0]["start"], "out": sents[1]["end"], "section": "intro", "transition": "fadeblack"},
            {"ref": "does-not-exist#9", "section": "build"},
            {"ref": cat[-1]["uid"], "in": -5, "out": 999, "section": "build", "transition": "zoomin", "effects": ["zoom_in", "explode"]},
        ], "overlays": [{"section": "intro", "text": "我做了个台灯", "kind": "caption"}], "notes": ["多拍点特写"]}
        edl = edl_from_llm(p, data, cat, sents, p.load(), p.style(), p.type_template())
        assert len(edl.clips) == 3                                  # invalid ref dropped
        last = edl.clips[-1]
        assert last.in_ >= cat[-1]["start"] and last.out <= cat[-1]["end"]   # clamped into the shot
        assert last.effects == [] and last.move is not None and last.move.type == "push_in"   # v1 flag → v2 move
        assert any("无效" in n for n in edl.notes)
        assert any(o.text == "我做了个台灯" for o in edl.overlays)
        with S.raises(PlanError):
            edl_from_llm(p, {"clips": [{"ref": "x"}]}, cat, sents, p.load(), p.style(), p.type_template())

    def test_make_plan_llm_and_fallback(self):
        analyzed_project = S.analyzed_project()
        monkeypatch = self.monkeypatch()
        import vcut.plan as plan_mod

        cat = build_catalog(analyzed_project)
        good = json.dumps({"clips": [{"ref": u["uid"], "section": "build"} for u in cat[:4]]})
        monkeypatch.setattr(plan_mod, "get_backend", lambda name: FakeBackend(good))
        edl = make_plan(analyzed_project, backend_name="fake", save=False)
        assert edl.planner.startswith("llm:fake") and len(edl.clips) == 4
        monkeypatch.setattr(plan_mod, "get_backend", lambda name: FakeBackend("我不会输出 JSON"))
        edl = make_plan(analyzed_project, backend_name="fake", save=False)
        assert edl.planner == "heuristic"                            # graceful fallback

    def test_vision_with_fake_backend(self):
        analyzed_project = S.analyzed_project()
        tmp_path = self.tmp_path()
        from vcut.analyze.pipeline import analyze_media

        def reply(prompt):
            import re
            idxs = [int(x) for x in re.findall(r"镜头 idx=(\d+)", prompt)]
            return json.dumps({"shots": [{"idx": i, "category": "demo" if i == 0 else "bogus", "description": f"镜头{i}",
                                          "tags": ["台灯"], "highlight": 0.9} for i in idxs]})

        p = analyzed_project
        m = next(m for m in p.media() if m["source_name"].startswith("PRO_VID"))
        fb = FakeBackend(reply)
        d = analyze_media(p, m, backend=fb, do_asr=False)
        assert d["stages"]["vision"]["model"] == "fake-vl"
        assert d["shots"][0]["vision"]["category"] == "demo"
        assert d["shots"][1]["vision"]["category"] == "broll"        # unknown category sanitized
        assert fb.prompts[0][1] >= 3                                 # keyframes were attached
        n = len(fb.prompts)
        analyze_media(p, m, backend=fb, do_asr=False)
        assert len(fb.prompts) == n                                  # cached, no new API calls

    def test_render_quick(self):
        analyzed_project = S.analyzed_project()
        edl = plan_heuristic(analyzed_project)
        edl.save(analyzed_project.edl_path)
        out = render(analyzed_project, edl, quick=True, workers=2)
        pi = probe(out)
        assert pi.has_video and pi.has_audio
        assert (pi.width, pi.height) == (960, 540)
        assert pi.duration == S.approx(edl.total_duration, abs=0.2)
        assert out.with_suffix(".srt").exists()

    def test_exports(self):
        analyzed_project = S.analyzed_project()
        tmp_path = self.tmp_path()
        edl = plan_heuristic(analyzed_project)
        x = export_fcpxml(analyzed_project, edl, tmp_path / "t.fcpxml")
        root = ET.parse(x).getroot()
        assert root.tag == "fcpxml" and len(root.findall(".//spine/asset-clip")) >= len(edl.clips)
        if not jianying_available():
            self.skipTest("pyJianYingDraft not installed")
        d = export_jianying(analyzed_project, edl, drafts_dir=tmp_path / "drafts", name="t")
        content = json.loads((d / "draft_content.json").read_text(encoding="utf-8"))
        types = [t["type"] for t in content["tracks"]]
        assert "video" in types and "text" in types and "audio" in types
        main = next(t for t in content["tracks"] if t["type"] == "video")
        assert len(main["segments"]) >= len(edl.clips)
        assert (d / "draft_meta_info.json").exists()

    def test_sponsored_vertical_project(self):
        tmp_path = self.tmp_path()
        media_dir = S.media_dir()
        """9:16 商单 with logo, brief, beat-synced energetic style, separate voiceover file."""
        from vcut.analyze import analyze_project
        from vcut.ingest import ingest
        from vcut.project import Project

        p = Project.create("品牌体验", "sponsored", parent=tmp_path)
        d = p.load()
        assert d["aspect"] == "9:16" and d["style"] == "energetic"
        d["sponsor"].update({"brand": "ACME", "must_show": ["包装"], "key_messages": ["续航 30 天", "一键配网"],
                             "logo": "assets/logo.png", "cta": "点击左下角了解更多"})
        d["target_duration"] = 20
        p.save(d)
        ingest(p, [media_dir], mode="link")
        vo = tmp_path / "vo.wav"
        shutil.copy(media_dir / "music" / "电子_科技" / "test_beat_120bpm.wav", vo)
        ingest(p, [vo], as_kind="voiceover")
        analyze_project(p, do_asr=False)
        edl = plan_heuristic(p)
        assert (edl.width, edl.height) == (1080, 1920)
        assert edl.logo is not None
        assert any(a.kind == "voiceover" for a in edl.audio)
        assert any("卡点" in n for n in edl.notes)
        assert any(o.text == "续航 30 天" for o in edl.overlays)
        assert any(o.kind == "cta" and "左下角" in o.text for o in edl.overlays)
        out = render(p, edl, quick=True, workers=2)
        pi = probe(out)
        assert (pi.width, pi.height) == (540, 960)

