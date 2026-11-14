"""Geometry and compositing invariants that protect the real footage."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
from PIL import Image


def module(name):
    path=Path(__file__).resolve().parents[1]/'skills/maker-cg/scripts'/f'{name}.py'
    spec=importlib.util.spec_from_file_location(name,path)
    result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result)
    return result


class SceneGeometryTests(unittest.TestCase):
    def test_nonplanar_depth_reprojects_through_a_rotated_camera(self):
        geometry=module('camera_geometry')
        K=np.array([[90.,0,32],[0,90.,24],[0,0,1.]])
        a=.37
        E=np.eye(4);E[:3,:3]=[[np.cos(a),0,np.sin(a)],[0,1,0],[-np.sin(a),0,np.cos(a)]]
        E[:3,3]=[.4,-.2,1.5]
        y,x=np.mgrid[:48,:64]
        depth=2+.4*np.sin(x/12)+y/90
        world=geometry.backproject(depth,K,E)
        camera=world@E[:3,:3].T+E[:3,3]
        pixels=camera@K.T
        pixels=pixels[:,:,:2]/pixels[:,:,2:]
        np.testing.assert_allclose(pixels,np.stack([x,y],axis=-1),atol=1e-9)

    def test_anchor_alignment_has_the_expected_orientation_and_scale(self):
        geometry=module('camera_geometry')
        y,x=np.mgrid[:80,:100]
        xyz=np.stack([x/50,-y/50,np.full_like(x,3.)],axis=-1)
        transform,height=geometry.align_to_anchor(xyz,{'plane':{'corners':[[.2,.2],[.8,.2],[.8,.8],[.2,.8]]}})
        mapped=np.c_[np.array([[.4,-.32,3],[1.6,-.32,3],[1.6,-1.28,3],[.4,-1.28,3]]),np.ones(4)]@transform.T
        np.testing.assert_allclose(mapped[:,:3],[[-.5,.4,0],[.5,.4,0],[.5,-.4,0],[-.5,-.4,0]],atol=1e-8)
        self.assertAlmostEqual(height,.8)


class SceneCompositeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        for folder in ['plate','cg','masks/1','masks/foreground']:(self.root/folder).mkdir(parents=True)
        self.original=np.full((64,64,3),[170,100,40],np.uint8)
        Image.fromarray(self.original).save(self.root/'plate/00000.png')
        Image.fromarray(np.full((64,64,4),[30,210,80,255],np.uint8)).save(self.root/'cg/00000.png')
        Image.fromarray(np.full((64,64,3),[15,30,180],np.uint8)).save(self.root/'clean-reference.png')
        Image.fromarray(np.full((64,64),255,np.uint8)).save(self.root/'masks/1/00000.png')
        foreground=np.zeros((64,64),np.uint8);foreground[16:32,16:32]=255
        Image.fromarray(foreground).save(self.root/'masks/foreground/00000.png')
        (self.root/'segmentation.json').write_text(json.dumps({'foreground':True}),encoding='utf-8')
        self.camera={'count':1,'fps':24,'width':64,'height':64}
        self.plan={'effect':{},'clean_plate':{'object_id':1}}

    def tearDown(self):self.temp.cleanup()

    def test_real_foreground_survives_both_clean_plate_and_cg(self):
        compositor=module('compositing').Compositor(self.plan,self.root,self.camera)
        frame=compositor.frame(0)
        np.testing.assert_array_equal(frame[16:32,16:32],self.original[16:32,16:32])
        self.assertGreater(np.abs(frame[2,2].astype(int)-self.original[2,2]).max(),50)

    def test_zero_envelope_restores_the_original_plate_exactly(self):
        self.plan['effect']['blend_envelope']=[[0,0],[1,0]]
        frame=module('compositing').Compositor(self.plan,self.root,self.camera).frame(0)
        np.testing.assert_array_equal(frame,self.original)

    def test_shadow_adjustment_keeps_opaque_objects_and_can_remove_extra_shadow(self):
        self.plan.pop('clean_plate')
        (self.root/'segmentation.json').write_text(json.dumps({'foreground':False}),encoding='utf-8')
        layer=np.zeros((64,64,4),np.uint8);layer[:,:,3]=160
        layer[20:40,20:40]=[30,210,80,255]
        Image.fromarray(layer).save(self.root/'cg/00000.png')
        matte=self.root/'object-matte';matte.mkdir()
        mask=np.zeros((64,64),np.uint8);mask[20:40,20:40]=255
        Image.fromarray(mask).save(matte/'00000.png')
        compositor=module('compositing').Compositor(self.plan,self.root,self.camera,shadow_folder=matte,shadow_strength=0)
        frame=compositor.frame(0)
        np.testing.assert_array_equal(frame[0,0],self.original[0,0])
        np.testing.assert_array_equal(frame[30,30],[30,210,80])


if __name__=='__main__':unittest.main()
