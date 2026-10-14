import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1] / "skills/storytelling/publishing"


class ManifestTests(unittest.TestCase):
    def test_requested_platforms_are_present_with_truthful_capabilities(self):
        manifest = json.loads((ROOT / "platforms.json").read_text())
        self.assertEqual(manifest["default_mode"], "local_preview")
        platforms = {p["id"]: p for p in manifest["platforms"]}
        self.assertEqual(len(platforms), len(manifest["platforms"]))
        self.assertEqual(set(platforms), {"wechat-official-account", "xiaohongshu", "csdn",
                         "aws-builder-center", "x", "wechat-channels", "douyin", "bilibili", "youtube"})
        for platform in platforms.values():
            self.assertTrue(platform["editor_url"].startswith("https://"))
            self.assertTrue(platform["references"])
            if platform["implementation"] == "runnable-python-adapter":
                self.assertTrue((ROOT / platform["entrypoint"]).is_file())
            else:
                self.assertGreaterEqual(len(platform["flow"]), 5)
                self.assertNotIn("entrypoint", platform)
        self.assertEqual(set(platforms["xiaohongshu"]["formats"]), {"image-carousel", "video"})
        self.assertEqual(platforms["wechat-official-account"]["bundle_ids"], ["wechat-article"])
        self.assertEqual(platforms["xiaohongshu"]["bundle_ids"], ["xiaohongshu", "xiaohongshu-video"])
        bundle_ids = [bundle for platform in platforms.values() for bundle in platform["bundle_ids"]]
        self.assertEqual(len(bundle_ids), len(set(bundle_ids)))
        self.assertEqual(len(bundle_ids), 10)


if __name__ == "__main__":
    unittest.main()
