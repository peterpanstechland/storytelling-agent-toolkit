"""Regression checks for the generic CG job, camera contracts and source protection."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

try:
    import cv2
    import numpy as np
except ImportError:
    cv2 = np = None


@unittest.skipIf(cv2 is None, 'Optional CG runtime needs OpenCV and NumPy.')
class GenericCGTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        script=Path(__file__).resolve().parents[1]/'skills/maker-cg/scripts/cg.py'
        spec=importlib.util.spec_from_file_location('maker_cg_under_test',script)
        cls.cg=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.cg)

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        (self.root/'source.mov').write_bytes(b'unchanged-original')
        (self.root/'music.mp3').write_bytes(b'authorized-test-music')
        self.plan=dict(source='source.mov',music='music.mp3',duration=4,fps=24,width=640,
                       color={'status':'normalized_sdr'},camera={'mode':'fixed'},effect={'preset':'portal'})

    def tearDown(self):
        self.temp.cleanup()

    def write_plan(self):
        file=self.root/'plan.json'
        file.write_text(json.dumps(self.plan),encoding='utf-8')
        return file

    def test_custom_scenes_work_without_a_product_preset_or_plane(self):
        script=self.root/'custom.py'
        script.write_text('def build_scene(context):\n    pass\n',encoding='utf-8')
        self.plan.pop('effect')
        self.plan['scene_script']='custom.py'
        with self.cg.job(self.write_plan(),self.root/'output') as plan:
            self.assertEqual(Path(plan['scene_script']),script)
            self.assertEqual(Path(plan['source']),self.root/'source.mov')
        self.assertEqual((self.root/'source.mov').read_bytes(),b'unchanged-original')
        self.assertFalse((self.root/'output/.running').exists())

    def test_unrelated_output_folder_is_preserved(self):
        out=self.root/'output'
        out.mkdir()
        file=out/'keep.txt'
        file.write_text('keep',encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'unrelated content'):
            with self.cg.job(self.write_plan(),out):
                self.fail('Must reject existing unrelated files')
        self.assertEqual(file.read_text(encoding='utf-8'),'keep')

    def test_changed_model_cannot_reuse_old_render_frames(self):
        asset=self.root/'model.glb'
        asset.write_bytes(b'first-model')
        self.plan['assets']={'hero':'model.glb'}
        plan=self.write_plan()
        out=self.root/'output'
        with self.cg.job(plan,out):
            pass
        asset.write_bytes(b'another-model')
        with self.assertRaisesRegex(ValueError,'changed'):
            with self.cg.job(plan,out):
                self.fail('A stale model must require a new render version')
        self.assertFalse((out/'.running').exists())

    def test_imported_camera_rejects_nonrigid_pose(self):
        transform=np.eye(4)
        transform[0,1]=.3
        data=dict(width=640,height=360,fps=24,K=[[600,0,320],[0,600,180],[0,0,1]],
                  frames=[{'frame':0,'camera_matrix':transform.tolist()}])
        file=self.root/'solved.json'
        file.write_text(json.dumps(data),encoding='utf-8')
        self.plan['camera']={'mode':'imported','file':str(file)}
        with self.assertRaisesRegex(ValueError,'rigid'):
            self.cg.supplied_camera(self.plan,640,360,24,1)

    def test_imported_camera_preserves_supplied_animation(self):
        frames=[]
        for frame in range(3):
            matrix=np.eye(4)
            matrix[0,3]=frame*.1
            matrix[2,3]=3
            frames.append(dict(frame=frame,camera_matrix=matrix.tolist()))
        data=dict(width=640,height=360,fps=24,K=[[600,0,320],[0,600,180],[0,0,1]],frames=frames)
        file=self.root/'solved.json'
        file.write_text(json.dumps(data),encoding='utf-8')
        self.plan['camera']={'mode':'imported','file':str(file)}
        actual=self.cg.supplied_camera(self.plan,640,360,24,3)
        self.assertEqual(actual['frames'],frames)
        self.assertEqual(actual['K'],data['K'])

    def test_fixed_camera_rejects_camera_motion(self):
        rng=np.random.default_rng(34)
        original=rng.integers(0,256,(480,640,3),dtype=np.uint8)
        original=cv2.GaussianBlur(original,(3,3),.7)
        moved=cv2.warpAffine(original,np.float32([[1,0,22],[0,1,0]]),(640,480))
        frames=[]
        for n in range(5):
            file=self.root/f'{n}.png'
            self.cg.save_image(file,original if n==0 else moved)
            frames.append(file)
        with self.assertRaisesRegex(ValueError,'Camera moves'):
            self.cg.check_fixed_camera(original,frames)


if __name__=='__main__':
    unittest.main()
