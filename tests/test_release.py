import importlib.util
from pathlib import Path
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('release',ROOT/'scripts/check_release.py');release=importlib.util.module_from_spec(spec);spec.loader.exec_module(release)
class ReleaseTests(unittest.TestCase):
 def test_media_not_publishable(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d);(p/'clip.mp4').write_bytes(bytes([0,255]));self.assertTrue(release.findings(p,['clip.mp4']))
 def test_token_caught_without_printing_secret(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d);(p/'config.txt').write_text('gh'+'p_'+'a'*36);issues=release.findings(p,['config.txt']);self.assertEqual(issues,[('config.txt','GitHub token')])
 def test_clean_text_passes(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d);(p/'guide.md').write_text('Portable storytelling.');self.assertEqual(release.findings(p,['guide.md']),[])
if __name__=='__main__':unittest.main()
