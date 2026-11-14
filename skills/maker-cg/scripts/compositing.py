"""One compositing path shared by preview frames and the final movie."""
import json
from pathlib import Path

import cv2
import numpy as np
from PIL import Image


class Compositor:
    def __init__(self,plan,folder,camera,foreground_frames=None,*,shadow_folder=None,shadow_strength=1):
        self.plan,self.folder,self.camera=plan,Path(folder),camera
        self.foreground_frames=foreground_frames
        self.shadow_folder=Path(shadow_folder) if shadow_folder else None
        self.shadow_strength=shadow_strength
        envelope=plan.get('effect',{}).get('blend_envelope')
        self.weights=np.interp(np.arange(camera['count'])/camera['fps'],*np.asarray(envelope).T) if envelope else np.ones(camera['count'])
        self.clean=None
        if plan.get('clean_plate'):
            self.clean=self.rgb(self.folder/'clean-reference.png')
            reference=cv2.cvtColor(np.uint8(self.rgb(self.folder/'plate/00000.png')*255),cv2.COLOR_RGB2GRAY)
            self.flow_scale=min(1,640/camera['width'])
            self.flow_size=(round(camera['width']*self.flow_scale),round(camera['height']*self.flow_scale))
            self.reference_small=cv2.resize(reference,self.flow_size)
            self.flow=cv2.DISOpticalFlow_create(cv2.DISOPTICAL_FLOW_PRESET_MEDIUM)
            self.yy,self.xx=np.mgrid[:camera['height'],:camera['width']].astype(np.float32)
        segmentation=self.folder/'segmentation.json'
        self.tracked_foreground=segmentation.exists() and json.loads(segmentation.read_text(encoding='utf-8')).get('foreground',False)

    @staticmethod
    def rgb(path):return np.asarray(Image.open(path).convert('RGB'),np.float32)/255

    def foreground(self,n):
        if self.foreground_frames:return self.foreground_frames[n]
        if self.tracked_foreground:return self.folder/f'masks/foreground/{n:05d}.png'
        manual=self.plan.get('foreground_mask')
        if manual and Path(manual).suffix.lower() in ('.png','.jpg','.jpeg','.webp'):return Path(manual)
        if manual:raise ValueError('Extract the foreground-mask video before compositing a preview.')
        return None

    def frame(self,n):
        original=self.rgb(self.folder/f'plate/{n:05d}.png')
        plate=original.copy()
        if self.clean is not None:
            gray=cv2.cvtColor(np.uint8(plate*255),cv2.COLOR_RGB2GRAY)
            flow=self.flow.calc(cv2.resize(gray,self.flow_size),self.reference_small,None)
            flow=cv2.resize(flow,(self.camera['width'],self.camera['height']))/self.flow_scale
            replacement=cv2.remap(self.clean,self.xx+flow[:,:,0],self.yy+flow[:,:,1],cv2.INTER_LINEAR,borderMode=cv2.BORDER_REFLECT)
            target=self.folder/f'masks/{self.plan["clean_plate"]["object_id"]}/{n:05d}.png'
            erase=np.asarray(Image.open(target).convert('L'),np.float32)/255
            erase=cv2.GaussianBlur(erase,(0,0),.65)[:,:,None]*self.weights[n]
            plate=plate*(1-erase)+replacement*erase
        layer=np.asarray(Image.open(self.folder/f'cg/{n:05d}.png').convert('RGBA'),np.float32)/255
        alpha=layer[:,:,3:4]
        radiance_ratio=1
        if self.shadow_folder:
            object_mask=np.asarray(Image.open(self.shadow_folder/f'{n:05d}.png').convert('L'),np.float32)[:,:,None]/255
            object_mask=np.minimum(object_mask,alpha)
            adjusted=object_mask+self.shadow_strength*(alpha-object_mask)
            radiance_ratio=np.where(object_mask>.001,alpha/np.maximum(adjusted,1e-6),1)
            alpha=adjusted
        alpha=alpha*self.weights[n]
        foreground=self.foreground(n)
        if foreground:
            mask=np.asarray(Image.open(foreground).convert('L'),np.float32)[:,:,None]/255
            alpha*=1-mask
            plate=plate*(1-mask)+original*mask
        linear=lambda a:np.where(a<=.04045,a/12.92,((a+.055)/1.055)**2.4)
        light=linear(layer[:,:,:3])*radiance_ratio*alpha+linear(plate)*(1-alpha)
        encoded=np.where(light<=.0031308,light*12.92,1.055*np.maximum(light,0)**(1/2.4)-.055)
        return np.uint8(np.clip(encoded,0,1)*255+.5)
