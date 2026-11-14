"""Build renderable/collidable Blender geometry from locally reconstructed source pixels."""
from pathlib import Path

import bpy
import numpy as np
from mathutils import Vector


def visible_mesh(ctx,name,*,mask=None,step=4,material=None,thickness=0,discontinuity=.035,support_mask=None,geometry='depth'):
    if '_visible_geometry' not in ctx:
        with np.load(ctx['job']/'perception.npz') as data:
            ctx['_visible_geometry']=data['xyz'].copy()
    xyz=ctx['_visible_geometry']
    h,w=xyz.shape[:2]
    if mask is not None and not isinstance(mask,np.ndarray):
        image=bpy.data.images.load(str(mask),check_existing=True)
        rgba=np.asarray(image.pixels[:],np.float32).reshape(image.size[1],image.size[0],4)
        region=np.flipud(rgba[:,:,0])>.5
        if region.shape!=(h,w):raise ValueError('Scene mask must match the source plate.')
    elif isinstance(mask,np.ndarray):region=mask.astype(bool)
    else:region=np.ones((h,w),bool)
    ys,xs=np.where(region)
    if not len(xs):raise ValueError('The observed scene region is empty.')
    x_indices=np.unique(np.r_[np.arange(xs.min(),xs.max()+1,step),xs.max()])
    y_indices=np.unique(np.r_[np.arange(ys.min(),ys.max()+1,step),ys.max()])
    xx,yy=np.meshgrid(x_indices,y_indices)
    points=xyz[yy,xx];valid=region[yy,xx]&np.isfinite(points).all(axis=-1)
    support=region if support_mask is None else support_mask
    if geometry=='plane':
        cloud=xyz[support]
        rng=np.random.default_rng(43)
        cloud=cloud[rng.choice(len(cloud),min(5000,len(cloud)),replace=False)]
        best=None;score=0
        for _ in range(100):
            a,b,c=cloud[rng.choice(len(cloud),3,replace=False)]
            normal=np.cross(b-a,c-a);normal/=max(np.linalg.norm(normal),1e-10)
            distance=np.abs((cloud-a)@normal)
            selected=distance<.025
            if selected.sum()>score:best=cloud[selected];score=selected.sum()
        center_plane=best.mean(axis=0)
        normal=np.linalg.svd(best-center_plane,full_matrices=False)[2][-1]
        camera=np.asarray(ctx['camera_data']['frames'][0]['camera_matrix'])[:3,3]
        rays=points-camera
        denominator=rays@normal
        factor=((center_plane-camera)@normal)/np.where(abs(denominator)<1e-7,1e-7,denominator)
        points=camera+rays*factor[:,:,None]
    columns=len(x_indices)
    faces=[]
    for row in range(len(y_indices)-1):
        for col in range(columns-1):
            cy=round((y_indices[row]+y_indices[row+1])/2);cx=round((x_indices[col]+x_indices[col+1])/2)
            if not region[cy,cx] or not np.isfinite(points[row:row+2,col:col+2]).all():continue
            if not support[yy[row:row+2,col:col+2],xx[row:row+2,col:col+2]].all():continue
            patch=points[row:row+2,col:col+2].reshape(-1,3)
            if np.linalg.norm(patch-patch[0],axis=1).max()>discontinuity:continue
            a=row*columns+col
            faces.extend([(a,a+columns,a+1),(a+1,a+columns,a+columns+1)])
    if not faces:raise ValueError('No connected scene surface survived mask/depth continuity checks.')
    mesh=bpy.data.meshes.new(name)
    center=np.median(points.reshape(-1,3),axis=0)
    mesh.from_pydata((points.reshape(-1,3)-center).tolist(),[],faces)
    mesh.update()
    obj=bpy.data.objects.new(name,mesh);ctx['scene'].collection.objects.link(obj);obj.location=center
    uv=mesh.uv_layers.new(name='Source photographic projection')
    coordinates=np.stack([xx/w,1-yy/h],axis=-1).reshape(-1,2)
    for face in mesh.polygons:
        face.use_smooth=True
        for loop in face.loop_indices:uv.data[loop].uv=coordinates[mesh.loops[loop].vertex_index]
    normals=mesh.attributes.new(name='source_rest_normal',type='FLOAT_VECTOR',domain='POINT')
    normals.data.foreach_set('vector',np.asarray([v.normal[:] for v in mesh.vertices],np.float32).ravel())
    if material:mesh.materials.append(material)
    if thickness:
        modifier=obj.modifiers.new('Observed surface volume','SOLIDIFY');modifier.thickness=thickness;modifier.offset=-1
        if len(mesh.materials)>1:modifier.material_offset=1;modifier.material_offset_rim=1
    obj['reconstruction']='Visible source depth mesh with depth-discontinuity rejection. Unseen surfaces unmeasured.'
    obj['source_step_pixels']=step
    obj['surface_model']=geometry
    return obj


def environment(ctx,*,exclude_object=None,step=5,shadow_catcher=True):
    mask=None
    if exclude_object is not None:
        source=bpy.data.images.load(str(ctx['job']/f'masks/{exclude_object}/00000.png'),check_existing=True)
        rgba=np.asarray(source.pixels[:],np.float32).reshape(source.size[1],source.size[0],4)
        rgba[:,:,:3]=1-rgba[:,:,:3]
        temporary=bpy.data.images.new('Environment exclusion mask',source.size[0],source.size[1],alpha=True)
        temporary.pixels=rgba.ravel();temporary.filepath_raw=str(ctx['job']/'environment-mask.png');temporary.file_format='PNG';temporary.save()
        mask=temporary.filepath_raw
    neutral=ctx['material']('Environment shadow receiver',(.45,.45,.45),0,.8)
    obj=visible_mesh(ctx,'Reconstructed environment',mask=mask,step=step,material=neutral,discontinuity=.12)
    if shadow_catcher:
        if ctx['scene'].render.engine!='CYCLES':raise ValueError('Physical environment shadow catching requires Cycles.')
        obj.is_shadow_catcher=True
    collision=obj.modifiers.new('Environment collision','COLLISION')
    return obj


def photograph_material(ctx):
    if '_photograph_material' not in ctx:
        temporary=ctx['source_surface']('Photograph material prototype',[[0,0],[1,0],[1,1],[0,1]],grid=1,thickness=0,relight=True)
        ctx['_photograph_material']=temporary.data.materials[0]
        bpy.data.objects.remove(temporary,do_unlink=True)
    return ctx['_photograph_material']
