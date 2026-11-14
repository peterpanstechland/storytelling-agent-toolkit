"""Construct editable, photo-textured surface geometry from the observed source frame."""
import math
from pathlib import Path

import bpy
import numpy as np
from mathutils import Matrix,Vector


def homography(quad):
    rows=[]
    rhs=[]
    for (u,v),(x,y) in zip([(0,0),(1,0),(1,1),(0,1)],quad):
        rows.extend([[u,v,1,0,0,0,-u*x,-v*x],[0,0,0,u,v,1,-u*y,-v*y]])
        rhs.extend([x,y])
    return np.r_[np.linalg.solve(rows,rhs),1].reshape(3,3)


def within(point,polygon):
    x,y=point
    inside=False
    for a,b in zip(polygon,polygon[1:]+polygon[:1]):
        if (a[1]>y)!=(b[1]>y) and x < (b[0]-a[0])*(y-a[1])/(b[1]-a[1])+a[0]:
            inside=not inside
    return inside


def add_source_surface(ctx,name,polygon,*,thickness=.008,depth=0,texture=None,side_material=None,grid=12,relight=False):
    data=ctx['camera_data']
    w,h=data['width'],data['height']
    quad=data['frames'][0].get('quad')
    if quad is None:
        normalized=ctx['plan'].get('plane',{}).get('corners',[[0,0],[1,0],[1,1],[0,1]])
        quad=np.asarray(normalized)*[w,h]
    warp=homography(quad)
    K=np.asarray(data['K'],float)
    world=np.asarray(data['frames'][0]['camera_matrix'],float)
    origin=world[:3,3]
    perception=ctx['job']/'perception.npz'
    if perception.exists() and '_source_xyz' not in ctx:
        with np.load(perception) as data:ctx['_source_xyz']=data['xyz'].copy()
    xyz=ctx.get('_source_xyz')

    def point(u,v):
        pixel=warp@np.array([u,v,1.])
        px,py=pixel[:2]/pixel[2]
        if xyz is not None:
            x=int(np.clip(round(px),0,w-1));y=int(np.clip(round(py),0,h-1))
            pos=xyz[y,x].copy()
        else:
            ray=world[:3,:3]@np.array([(px-K[0,2])/K[0,0],-(py-K[1,2])/K[1,1],-1.])
            pos=origin+ray*(-origin[2]/ray[2])
        return tuple(pos+np.array([0,0,depth])),(px/w,1-py/h)

    polygon=[list(p) for p in polygon]
    u0,v0=np.min(polygon,axis=0)
    u1,v1=np.max(polygon,axis=0)
    vertices=[]
    image_uv=[]
    plane_uv=[]
    for row in range(grid+1):
        for col in range(grid+1):
            u=u0+(u1-u0)*col/grid
            v=v0+(v1-v0)*row/grid
            p,uv=point(u,v)
            vertices.append(p);image_uv.append(uv);plane_uv.append((u,1-v))
    faces=[]
    for row in range(grid):
        for col in range(grid):
            if within((u0+(u1-u0)*(col+.5)/grid,v0+(v1-v0)*(row+.5)/grid),polygon):
                a=row*(grid+1)+col
                faces.append((a,a+grid+1,a+grid+2,a+1))
    if not faces:
        raise ValueError('Observed source region is empty at the selected mesh resolution.')
    mesh=bpy.data.meshes.new(name)
    mesh.from_pydata(vertices,[],faces)
    mesh.update()
    normals=mesh.attributes.new(name='source_rest_normal',type='FLOAT_VECTOR',domain='POINT')
    normals.data.foreach_set('vector',np.asarray([v.normal[:] for v in mesh.vertices],np.float32).ravel())
    obj=bpy.data.objects.new(name,mesh)
    ctx['scene'].collection.objects.link(obj)
    uv=mesh.uv_layers.new(name='Observed image coordinates')
    coordinates=plane_uv if texture else image_uv
    for face in mesh.polygons:
        for loop in face.loop_indices:
            uv.data[loop].uv=coordinates[mesh.loops[loop].vertex_index]

    # The camera background uses an image SEQUENCE. A material must have its own
    # FILE datablock or its UVs will silently sample changing camera pixels.
    texture_path=str(Path(texture or ctx['job']/'plate/00000.png').resolve())
    photographs=ctx.setdefault('_photograph_images',{})
    if texture_path not in photographs:
        photograph=bpy.data.images.load(texture_path,check_existing=False)
        photograph.source='FILE'
        photographs[texture_path]=photograph
    image=photographs[texture_path]
    mat=bpy.data.materials.new(name+' photographed surface')
    mat.use_nodes=True
    nodes=mat.node_tree.nodes
    nodes.clear()
    source=nodes.new('ShaderNodeTexImage');source.image=image
    emission=nodes.new('ShaderNodeEmission');emission.inputs['Strength'].default_value=1
    output=nodes.new('ShaderNodeOutputMaterial')
    color=source.outputs['Color']
    if relight:
        # Preserve the source exposure at the observed normal while allowing new
        # orientations and nearby geometry to change the photographed radiance.
        lighting=ctx['plan'].get('scene_analysis',{}).get('lighting',{})
        direction=Vector(lighting.get('world_direction',[-.7,.9,2.4])).normalized()
        ambient=float(lighting.get('ambient_fraction',.45))
        normal=nodes.new('ShaderNodeNewGeometry')
        dot=nodes.new('ShaderNodeVectorMath');dot.operation='DOT_PRODUCT'
        dot.inputs[1].default_value=direction
        mat.node_tree.links.new(normal.outputs['Normal'],dot.inputs[0])
        positive=nodes.new('ShaderNodeMath');positive.operation='MAXIMUM';positive.inputs[1].default_value=0
        mat.node_tree.links.new(dot.outputs['Value'],positive.inputs[0])
        reference_normal=nodes.new('ShaderNodeAttribute');reference_normal.attribute_name='source_rest_normal'
        rest_dot=nodes.new('ShaderNodeVectorMath');rest_dot.operation='DOT_PRODUCT';rest_dot.inputs[1].default_value=direction
        mat.node_tree.links.new(reference_normal.outputs['Vector'],rest_dot.inputs[0])
        rest_positive=nodes.new('ShaderNodeMath');rest_positive.operation='MAXIMUM';rest_positive.inputs[1].default_value=0
        mat.node_tree.links.new(rest_dot.outputs['Value'],rest_positive.inputs[0])
        lit=nodes.new('ShaderNodeMath');lit.operation='MULTIPLY_ADD';lit.inputs[1].default_value=1-ambient;lit.inputs[2].default_value=ambient
        base=nodes.new('ShaderNodeMath');base.operation='MULTIPLY_ADD';base.inputs[1].default_value=1-ambient;base.inputs[2].default_value=ambient
        mat.node_tree.links.new(positive.outputs[0],lit.inputs[0]);mat.node_tree.links.new(rest_positive.outputs[0],base.inputs[0])
        ratio=nodes.new('ShaderNodeMath');ratio.operation='DIVIDE'
        mat.node_tree.links.new(lit.outputs[0],ratio.inputs[0]);mat.node_tree.links.new(base.outputs[0],ratio.inputs[1])
        occlusion=nodes.new('ShaderNodeAmbientOcclusion')
        occlusion.inputs['Distance'].default_value=float(lighting.get('occlusion_distance',.16))
        occlusion.samples=16
        ao=nodes.new('ShaderNodeMath');ao.operation='MULTIPLY_ADD'
        ao.inputs[1].default_value=.45;ao.inputs[2].default_value=.55
        mat.node_tree.links.new(occlusion.outputs['AO'],ao.inputs[0])
        attenuation=nodes.new('ShaderNodeMath');attenuation.operation='MULTIPLY'
        mat.node_tree.links.new(ratio.outputs[0],attenuation.inputs[0])
        mat.node_tree.links.new(ao.outputs[0],attenuation.inputs[1])
        tinted=nodes.new('ShaderNodeMixRGB');tinted.blend_type='MULTIPLY';tinted.inputs[0].default_value=1
        mat.node_tree.links.new(color,tinted.inputs[1])
        mat.node_tree.links.new(attenuation.outputs[0],tinted.inputs[2])
        color=tinted.outputs[0]
    mat.node_tree.links.new(color,emission.inputs['Color'])
    mat.node_tree.links.new(emission.outputs[0],output.inputs['Surface'])
    mesh.materials.append(mat)
    if side_material:
        mesh.materials.append(side_material)
    if thickness:
        modifier=obj.modifiers.new('Observed surface thickness','SOLIDIFY')
        modifier.thickness=thickness
        modifier.offset=-1
        modifier.material_offset=1 if side_material else 0
        modifier.material_offset_rim=1 if side_material else 0
    center=np.mean(vertices,axis=0)
    obj.location=center
    for vertex in mesh.vertices:
        vertex.co-=Vector(center)
    obj['geometry_source']='Source RGB projection and visible relative-depth mesh' if xyz is not None else 'Observed source region projected onto tracked plane'
    return obj
