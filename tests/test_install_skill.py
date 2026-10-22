import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('install_skill',ROOT/'scripts/install_skill.py')
install_skill=importlib.util.module_from_spec(spec);spec.loader.exec_module(install_skill)

def run_install(*args):
 argv=sys.argv
 try:
  sys.argv=['install_skill.py',*args]
  install_skill.main()
 finally:
  sys.argv=argv

class InstallSkillTests(unittest.TestCase):
 def test_default_copies_storytelling_only(self):
  with tempfile.TemporaryDirectory() as d:
   run_install('--target',d)
   self.assertTrue((Path(d)/'storytelling/SKILL.md').is_file())
   self.assertFalse((Path(d)/'pxl').exists())
 def test_pxl_copy_keeps_license(self):
  with tempfile.TemporaryDirectory() as d:
   run_install('--skill','pxl','--target',d)
   skill=Path(d)/'pxl'
   self.assertTrue((skill/'SKILL.md').is_file())
   self.assertIn('Copyright (c) 2026 crsolver',(skill/'LICENSE').read_text())
   self.assertTrue((skill/'bin/pxl.js').is_file())
   self.assertFalse((skill/'node_modules').exists())
if __name__=='__main__':unittest.main()
