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
 def test_pxl_example_art_is_allowed_and_other_images_are_not(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)
   gif=p/'skills/pxl/docs/gallery/cat.gif'
   gif.parent.mkdir(parents=True)
   gif.write_bytes(b'GIF89a'+bytes([255,0,1]))
   self.assertEqual(release.findings(p,['skills/pxl/docs/gallery/cat.gif']),[])
   (p/'clip.png').write_bytes(b'\x89PNG\r\n\x1a\n')
   self.assertTrue(any(reason=='not an approved source-text extension' for _,reason in release.findings(p,['clip.png'])))
   huge=p/'skills/pxl/docs/gallery/huge.gif'
   huge.write_bytes(b'GIF89a'+b'\x00'*(release.PXL_MEDIA_MAX))
   self.assertTrue(any('size budget' in reason for _,reason in release.findings(p,['skills/pxl/docs/gallery/huge.gif'])))
if __name__=='__main__':unittest.main()
