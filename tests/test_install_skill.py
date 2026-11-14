import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
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
 def test_cg_copy_contains_runtime_and_scene_resources(self):
  with tempfile.TemporaryDirectory() as d:
   run_install('--skill','maker-cg','--target',d)
   skill=Path(d)/'maker-cg'
   self.assertTrue((skill/'scripts/cg.py').is_file())
   self.assertTrue((skill/'scripts/blender_scene.py').is_file())
   self.assertTrue((skill/'references/runtime-setup.md').is_file())
   self.assertTrue((skill/'runtime.example.json').is_file())
   self.assertFalse((skill/'runtime.local.json').exists())
 def test_cg_copy_does_not_transfer_private_runtime(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);source=root/'repo/skills/maker-cg';source.mkdir(parents=True)
   for name in ('SKILL.md','runtime.example.json','runtime.local.json','scene-runtime.private.json'):
    (source/name).write_text('fixture',encoding='utf-8')
   (source/'.runtime').mkdir();(source/'.runtime/private.txt').write_text('fixture')
   with patch.object(install_skill,'__file__',str(root/'repo/scripts/install_skill.py')):
    run_install('--skill','maker-cg','--target',str(root/'installed'))
   installed=root/'installed/maker-cg'
   self.assertTrue((installed/'runtime.example.json').exists())
   self.assertFalse((installed/'runtime.local.json').exists())
   self.assertFalse((installed/'scene-runtime.private.json').exists())
   self.assertFalse((installed/'.runtime').exists())
if __name__=='__main__':unittest.main()
