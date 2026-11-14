"""Blender worker. All geometry, cameras and animation are native and saved in the blend."""
import argparse
import importlib.util
import json
import math
from pathlib import Path
import random
import sys

import bpy
from mathutils import Matrix, Vector


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--job',type=Path,required=True)
    parser.add_argument('--still',type=int)
    args=parser.parse_args(sys.argv[sys.argv.index('--')+1:])
    folder=args.job
    data=json.loads((folder/'camera.json').read_text(encoding='utf-8'))
    plan=data['plan']
    fps=data['fps']
    count=data['count']
    duration=count/fps
    random.seed(plan['effect'].get('seed',3114))
    scene=bpy.context.scene
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    render_settings=plan.get('render',{})
    if render_settings.get('engine','eevee')=='cycles':
        scene.render.engine='CYCLES'
        scene.cycles.samples=int(render_settings.get('samples',32))
        scene.cycles.use_denoising=True
        scene.cycles.max_bounces=5
        preferences=bpy.context.preferences.addons['cycles'].preferences
        preferences.compute_device_type='OPTIX'
        preferences.get_devices()
        wanted=render_settings.get('gpu','3080 Ti')
        enabled=False
        for device in preferences.devices:
            device.use=device.type=='OPTIX' and wanted in device.name
            enabled=enabled or device.use
        if not enabled:raise ValueError('The requested Cycles GPU is unavailable; choose an actual device.')
        scene.cycles.device='GPU'
    else:
        scene.render.engine='BLENDER_EEVEE'
        scene.eevee.use_fast_gi=True
    scene.render.resolution_x=data['width']
    scene.render.resolution_y=data['height']
    scene.render.resolution_percentage=100
    scene.render.pixel_aspect_y=data['K'][0][0]/data['K'][1][1]
    scene.render.fps=fps
    scene.frame_start=1
    scene.frame_end=count
    scene.render.film_transparent=True
    scene.render.image_settings.file_format='PNG'
    scene.render.image_settings.color_mode='RGBA'
    scene.render.image_settings.color_depth='8'
    scene.view_settings.view_transform='Standard'
    scene.view_settings.look='None'
    if hasattr(scene,'eevee') and hasattr(scene.eevee,'taa_render_samples'):
        scene.eevee.taa_render_samples=32
    if hasattr(scene.render,'use_motion_blur'):
        scene.render.use_motion_blur=True
        scene.render.motion_blur_shutter=.23
    world=bpy.data.worlds.new('Workbench ambient')
    scene.world=world
    world.use_nodes=True
    world.node_tree.nodes['Background'].inputs['Color'].default_value=(.16,.21,.19,1)
    world.node_tree.nodes['Background'].inputs['Strength'].default_value=.32

    cam_data=bpy.data.cameras.new('Measured camera')
    camera=bpy.data.objects.new('Measured camera',cam_data)
    scene.collection.objects.link(camera)
    scene.camera=camera
    cam_data.type='PERSP'
    cam_data.sensor_fit='HORIZONTAL'
    cam_data.sensor_width=36
    cam_data.lens=data['K'][0][0]/data['width']*36
    cam_data.shift_x=(data['width']/2-data['K'][0][2])/data['width']
    cam_data.shift_y=(data['K'][1][2]-data['height']/2)/data['width']
    cam_data.clip_start=.01
    cam_data.clip_end=100
    camera.rotation_mode='QUATERNION'
    for row in data['frames']:
        camera.matrix_world=Matrix(row['camera_matrix'])
        frame=row['frame']+1
        camera.keyframe_insert('location',frame=frame)
        camera.keyframe_insert('rotation_quaternion',frame=frame)
    # Standard Blender background-image reference is included in the editable scene.
    cam_data.show_background_images=True
    reference=cam_data.background_images.new()
    reference.image=bpy.data.images.load(str(folder/'plate/00000.png'),check_existing=True)
    reference.image.source='SEQUENCE'
    reference.image_user.frame_duration=count
    reference.image_user.frame_start=1
    reference.image_user.use_auto_refresh=True
    reference.alpha=.75

    def material(name,color,metallic=.18,roughness=.3,emission=0):
        mat=bpy.data.materials.new(name)
        mat.use_nodes=True
        node=mat.node_tree.nodes.get('Principled BSDF')
        linear=lambda x:x/12.92 if x<=.04045 else ((x+.055)/1.055)**2.4
        rgba=(*[linear(x) for x in color],1)
        node.inputs['Base Color'].default_value=rgba
        node.inputs['Metallic'].default_value=metallic
        node.inputs['Roughness'].default_value=roughness
        node.inputs['Emission Color'].default_value=rgba
        node.inputs['Emission Strength'].default_value=emission
        return mat

    jade=material('Jade enamel',(.26,.72,.41),.24,.24)
    mint=material('Mint porcelain',(.67,.92,.67),.1,.29)
    gold=material('Warm pollen',(.97,.66,.16),.3,.26,.22)
    cream=material('Petal ivory',(.99,.91,.59),.07,.27,.12)
    dark=material('Dark inner surface',(.025,.055,.045),.5,.36)
    glow=material('Living light',(.78,.99,.56),.07,.25,2.8)

    def cube(name,at,dimensions,mat,bevel=.003):
        bpy.ops.mesh.primitive_cube_add(size=1,location=at)
        obj=bpy.context.object
        obj.name=name
        obj.dimensions=dimensions
        bpy.ops.object.transform_apply(location=False,rotation=False,scale=True)
        obj.data.materials.append(mat)
        if bevel:
            modifier=obj.modifiers.new('Soft manufactured edges','BEVEL')
            modifier.width=bevel
            modifier.segments=2
        return obj

    def pose(obj,seconds,location=None,rotation=None,scale=1):
        frame=1+round(seconds*fps)
        if location is not None:
            obj.location=location
            obj.keyframe_insert('location',frame=frame)
        if rotation is not None:
            obj.rotation_euler=rotation
            obj.keyframe_insert('rotation_euler',frame=frame)
        obj.scale=(scale,scale,scale)
        obj.keyframe_insert('scale',frame=frame)

    def bloom(obj,start=1.8,full=3.4,leave=6.1):
        pose(obj,0,scale=.0001)
        pose(obj,start,scale=.0001)
        pose(obj,full,scale=1)
        pose(obj,leave,scale=1)
        pose(obj,duration-.35,scale=.0001)

    def tube(name,points,radius,mat):
        curve=bpy.data.curves.new(name,'CURVE')
        curve.dimensions='3D'
        curve.bevel_depth=radius
        curve.bevel_resolution=3
        spline=curve.splines.new('BEZIER')
        spline.bezier_points.add(len(points)-1)
        for p,xyz in zip(spline.bezier_points,points):
            p.co=xyz
            p.handle_left_type='AUTO'
            p.handle_right_type='AUTO'
        obj=bpy.data.objects.new(name,curve)
        scene.collection.objects.link(obj)
        obj.data.materials.append(mat)
        return obj

    def light(name,at,energy,color,size):
        lamp=bpy.data.lights.new(name,'AREA')
        lamp.energy=energy
        lamp.color=color
        lamp.shape='DISK'
        lamp.size=size
        obj=bpy.data.objects.new(name,lamp)
        scene.collection.objects.link(obj)
        obj.location=at
        direction=Matrix.Translation((0,-.2,.1)).translation-obj.location
        obj.rotation_euler=direction.to_track_quat('-Z','Y').to_euler()

    lighting=plan.get('scene_analysis',{}).get('lighting',{})
    if lighting.get('area_lights'):
        for lamp in lighting['area_lights']:
            light(lamp['name'],lamp['location'],lamp['energy'],lamp['color'],lamp['size'])
    else:
        light('Window key',(-2.8,3.5,4),420,(.87,1,.88),3.5)
        light('Warm workbench bounce',(2,-1.5,3),170,(1,.72,.42),2.7)
        light('Screen rim',(.7,.5,-.4),85,(.30,.76,1),1.8)
    if lighting.get('hdri_asset'):
        image=bpy.data.images.load(str(plan['assets'][lighting['hdri_asset']]),check_existing=True)
        environment=world.node_tree.nodes.new('ShaderNodeTexEnvironment');environment.image=image
        world.node_tree.links.new(environment.outputs['Color'],world.node_tree.nodes['Background'].inputs['Color'])
        world.node_tree.nodes['Background'].inputs['Strength'].default_value=float(lighting.get('environment_strength',1))
    preset='custom' if plan.get('scene_script') else plan['effect']['preset']
    clock=duration/8

    # Built-ins use a normalized local stage. Placement maps it onto any chosen surface.
    if preset!='custom':
        backing=cube('Inner recess',(0,-.265,.004),(.66,.43,.009),dark,.005)
        bloom(backing,.65*clock,1.45*clock,6.7*clock)
    if preset in ('voxel-bloom','voxel-scatter'):
        for row in range(7):
            for col in range(13):
                index=row*13+col
                sample=data['palette'][index]
                tint=tuple(min(1,.4*sample[i]+.6*(.14,.57,.26)[i]) for i in range(3))
                mat=material(f'Photographed tile {index}',tint,.22,.3)
                x=-.31+col*.62/12
                y=-.06-row*.39/6
                initial=(x,y,.038)
                obj=cube(f'Voxel {index:03}',initial,(.047,.056,.036),mat,.003)
                angle=index*2.3999632
                radius=.37+.10*random.random()
                opened=(math.cos(angle)*radius, -.24+math.sin(angle)*radius*.79,
                        .11+.29*random.random())
                angle3=tuple(random.uniform(-1.9,1.9) for _ in range(3))
                pose(obj,0,location=initial,rotation=(0,0,0),scale=.0001)
                pose(obj,.62*clock,location=initial,rotation=(0,0,0),scale=.0001)
                pose(obj,1.1*clock,location=initial,rotation=(0,0,0))
                pose(obj,(2.25+random.random()*.28)*clock,location=opened,rotation=angle3,scale=.85)
                drift=(opened[0]*1.05,opened[1]+.045,opened[2]+.04)
                pose(obj,5.3*clock,location=drift,rotation=tuple(v+.6 for v in angle3),scale=.85)
                pose(obj,6.6*clock,location=initial,rotation=(0,0,0))
                pose(obj,7.35*clock,location=initial,rotation=(0,0,0),scale=.0001)

    if preset=='voxel-bloom':
        # A fully modeled flower garden grows out along the plane's +Z, toward the camera.
        for stem_index,(x,y,z,height) in enumerate([(-.12,-.41,.23,.45),(.12,-.39,.30,.36),(.015,-.40,.42,.28)]):
            stalk=tube(f'Stem {stem_index}',[(x,y,z),(x-.018,y+height*.5,z+.015),(x+.012,y+height,z+.045)],.010,jade)
            bloom(stalk,1.65*clock,3.1*clock,6.15*clock)
            for j,side in enumerate([-1,1]):
                leaf=cube(f'Leaf {stem_index}-{j}',(x+side*.055,y+height*(.30+j*.22),z+.028),(.13,.047,.029),mint,.009)
                leaf.rotation_euler=(.4*side,.2,-.42*side)
                bloom(leaf,(2+j*.14)*clock,(3.4+j*.12)*clock,6.0*clock)
            center=(x+.012,y+height,z+.045)
            seed=cube(f'Flower heart {stem_index}',center,(.061,.061,.050),gold,.007)
            bloom(seed,2.4*clock,3.5*clock,6.0*clock)
            for petal in range(7):
                a=petal*math.tau/7
                pet=cube(f'Petal {stem_index}-{petal}',
                         (center[0]+math.cos(a)*.065,center[1]+math.sin(a)*.065,center[2]-.008),
                         (.063,.039,.028),cream,.010)
                pet.rotation_euler=(0,0,a)
                bloom(pet,(2.5+petal*.045)*clock,(3.65+petal*.035)*clock,5.9*clock)
        for i in range(36):
            angle=i*2.3999632
            r=.20+.13*random.random()
            pt=cube(f'Pollen {i}',(r*math.cos(angle),-.16+r*math.sin(angle),.12+random.random()*.36),(.010,.010,.010),glow,.002)
            bloom(pt,(2.0+random.random()*.6)*clock,(3.2+random.random()*.8)*clock,5.8*clock)
    elif preset=='portal':
        for ring in range(3):
            r=.20+ring*.046
            points=[(r*math.cos(i*math.tau/96),-.23+r*math.sin(i*math.tau/96),.08+ring*.026) for i in range(97)]
            obj=tube(f'Portal ring {ring}',points,.007 if ring!=1 else .012,glow if ring!=1 else gold)
            bloom(obj,.6*clock,(1.7+ring*.16)*clock,6.3*clock)
        for i in range(60):
            a=i*math.tau/60
            r=.27
            obj=cube(f'Portal fragment {i}',(r*math.cos(a),-.23+r*math.sin(a),.10),(.018,.018,.025),mint,.002)
            bloom(obj,(1.0+i/110)*clock,(2.0+i/100)*clock,6.1*clock)

    def import_model(name):
        file=Path(plan.get('assets',{})[name])
        before=set(scene.objects)
        if file.suffix.lower() in ('.glb','.gltf'):
            bpy.ops.import_scene.gltf(filepath=str(file))
        elif file.suffix.lower()=='.obj':
            bpy.ops.wm.obj_import(filepath=str(file))
        elif file.suffix.lower()=='.fbx':
            bpy.ops.import_scene.fbx(filepath=str(file))
        else:
            raise ValueError('Use GLB/GLTF, OBJ or FBX for imported models.')
        return [obj for obj in scene.objects if obj not in before]

    if preset=='custom':
        script=Path(plan['scene_script'])
        spec=importlib.util.spec_from_file_location('project_cg_scene',script)
        module=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        context=dict(bpy=bpy,scene=scene,camera=camera,job=folder,plan=plan,fps=fps,duration=duration,camera_data=data,
                     material=material,cube=cube,tube=tube,pose=pose,bloom=bloom,import_model=import_model)
        surface_spec=importlib.util.spec_from_file_location('cg_source_geometry',Path(__file__).with_name('source_geometry.py'))
        surface_module=importlib.util.module_from_spec(surface_spec)
        surface_spec.loader.exec_module(surface_module)
        context['source_surface']=lambda name,polygon,**options:surface_module.add_source_surface(context,name,polygon,**options)
        environment_spec=importlib.util.spec_from_file_location('cg_scene_environment',Path(__file__).with_name('scene_environment.py'))
        environment_module=importlib.util.module_from_spec(environment_spec);environment_spec.loader.exec_module(environment_module)
        context['visible_mesh']=lambda name,**options:environment_module.visible_mesh(context,name,**options)
        context['environment_mesh']=lambda **options:environment_module.environment(context,**options)
        context['photograph_material']=lambda:environment_module.photograph_material(context)
        effects_spec=importlib.util.spec_from_file_location('cg_surface_effects',Path(__file__).with_name('surface_effects.py'))
        effects_module=importlib.util.module_from_spec(effects_spec);effects_spec.loader.exec_module(effects_module)
        context['fracture']=lambda object_id,**options:effects_module.fracture(context,object_id,**options)
        module.build_scene(context)

    # Preserve imported armatures and nested models by parenting only their top-level nodes.
    rig=bpy.data.objects.new('CG volume',None)
    scene.collection.objects.link(rig)
    for obj in list(scene.objects):
        if obj!=rig and obj.type not in ('CAMERA','LIGHT') and obj.parent is None:
            obj.parent=rig
    placement=plan['effect'].get('placement',{})
    anchor=placement.get('center_uv',[.5,.5])
    size=float(placement.get('size',.82))
    rig.scale=(size,size,size)
    origin=placement.get('local_origin',[0,-.22,0] if preset!='custom' else [0,0,0])
    rig.rotation_euler=tuple(math.radians(v) for v in placement.get('rotation_degrees',[0,0,0]))
    target=Vector((anchor[0]-.5,data['plane_height']*(.5-anchor[1]),float(placement.get('depth',.012))))
    rig.location=target-rig.rotation_euler.to_matrix()@(Vector(origin)*size)

    # Keep the actual source and its estimated calibration with the native scene.
    source_note=bpy.data.texts.new('CG_JOB.json')
    source_note.write(json.dumps(dict(plan=plan,tracking=data['method'],intrinsics=data['intrinsics']),ensure_ascii=False,indent=2))
    bpy.ops.wm.save_as_mainfile(filepath=str(folder/'tracked-effect.blend'))
    out=folder/'cg'
    out.mkdir(exist_ok=True)
    targets=[args.still] if args.still is not None else range(count)
    for n in targets:
        target=out/f'{n:05d}.png'
        if target.exists():
            continue
        scene.frame_set(n+1)
        scene.render.filepath=str(target)
        bpy.ops.render.render(write_still=True)
        print(f'CG frame {n+1}/{count}',flush=True)


if __name__=='__main__':main()
