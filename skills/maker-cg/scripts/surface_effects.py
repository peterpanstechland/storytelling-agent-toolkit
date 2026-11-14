"""Effects driven by observed object masks and reconstructed geometry, not a product template."""
import math
import json
from pathlib import Path

import bpy
import numpy as np
from mathutils import Vector


def read_mask(path):
    image=bpy.data.images.load(str(path),check_existing=True)
    pixels=np.asarray(image.pixels[:],np.float32).reshape(image.size[1],image.size[0],4)
    return np.flipud(pixels[:,:,0])>.5


def fracture(ctx,object_id,*,pieces=28,seed=41,spread=.3,lift=.2,thickness=.015,
             start=.6,opened=1.8,hold=2.4,closed=3.5,geometry='depth',mesh_step=3,rotation_amount=.6):
    region=read_mask(ctx['job']/f'masks/{object_id}/00000.png')
    y,x=np.where(region)
    if len(x)<pieces*30:raise ValueError('Observed object is too small for this many fragments.')
    random=np.random.default_rng(seed)
    # Farthest-point sampling makes cuts follow the actual silhouette at a useful scale.
    candidates=np.stack([x,y],axis=1)[random.choice(len(x),min(len(x),8000),replace=False)]
    seeds=[candidates[random.integers(len(candidates))]]
    distances=np.full(len(candidates),np.inf)
    for _ in range(pieces-1):
        distances=np.minimum(distances,((candidates-seeds[-1])**2).sum(axis=1))
        seeds.append(candidates[distances.argmax()])
    seeds=np.asarray(seeds)
    assignment=np.full(region.shape,-1,np.int16)
    pixels=np.stack([x,y],axis=1)
    for block in range(0,len(x),20000):
        chunk=pixels[block:block+20000]
        labels=((chunk[:,None,:]-seeds[None,:,:])**2).sum(axis=2).argmin(axis=1)
        assignment[chunk[:,1],chunk[:,0]]=labels
    material=ctx['photograph_material']()
    report=json.loads((ctx['job']/'segmentation.json').read_text(encoding='utf-8'))
    color=report['objects'][str(object_id)].get('observed_material_rgb',[.18,.18,.18])
    side=ctx['material']('Observed material on cut edges',color,.02,.55)
    output=[]
    for i in range(pieces):
        mask=assignment==i
        if mask.sum()<30:continue
        obj=ctx['visible_mesh'](f'Observed fragment {i:03d}',mask=mask,step=mesh_step,material=material,
                                thickness=thickness,discontinuity=.12,support_mask=region,geometry=geometry)
        obj.data.materials.append(side)
        solid=obj.modifiers.get('Observed surface volume')
        if solid:solid.material_offset=1;solid.material_offset_rim=1
        bevel=obj.modifiers.new('Physical fracture edge','BEVEL');bevel.width=.0015;bevel.segments=2
        output.append(obj)
    center=np.mean([obj.location[:] for obj in output],axis=0)
    for i,obj in enumerate(output):
        rest=np.asarray(obj.location[:])
        radial=rest-center
        radial[2]*=.15
        radial/=max(np.linalg.norm(radial),.01)
        normal=np.mean([v.normal[:] for v in obj.data.vertices],axis=0)
        normal/=max(np.linalg.norm(normal),.01)
        delta=radial*spread+normal*lift
        position=rest+delta
        rotation=random.uniform(-rotation_amount,rotation_amount,3)
        delay=.14*i/max(len(output)-1,1)
        ctx['pose'](obj,0,location=rest,rotation=(0,0,0))
        ctx['pose'](obj,start+delay,location=rest,rotation=(0,0,0))
        ctx['pose'](obj,opened+delay,location=position,rotation=rotation)
        ctx['pose'](obj,hold+delay,location=position+normal*.025,rotation=rotation*1.08)
        ctx['pose'](obj,closed+delay,location=rest,rotation=(0,0,0))
    return output
