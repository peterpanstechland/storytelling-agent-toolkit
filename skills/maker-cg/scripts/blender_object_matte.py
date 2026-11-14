"""Render object coverage separately from photographed-environment shadow coverage."""
import argparse
from pathlib import Path
import sys
import bpy

parser=argparse.ArgumentParser()
parser.add_argument('--out',type=Path,required=True)
args=parser.parse_args(sys.argv[sys.argv.index('--')+1:])
args.out.mkdir(parents=True,exist_ok=True)
scene=bpy.context.scene
scene.render.engine='BLENDER_EEVEE'
scene.eevee.taa_render_samples=16
scene.eevee.use_fast_gi=False
scene.render.film_transparent=False
scene.render.image_settings.file_format='PNG'
scene.render.image_settings.color_mode='RGB'
scene.view_settings.view_transform='Standard';scene.view_settings.look='None'
scene.camera.data.show_background_images=False
world=bpy.data.worlds.new('Matte black background');world.use_nodes=True;scene.world=world
world.node_tree.nodes['Background'].inputs['Color'].default_value=(0,0,0,1)

def emission(name,color):
    material=bpy.data.materials.new(name);material.use_nodes=True
    nodes=material.node_tree.nodes;nodes.clear()
    surface=nodes.new('ShaderNodeEmission');surface.inputs['Color'].default_value=(*color,1)
    output=nodes.new('ShaderNodeOutputMaterial');material.node_tree.links.new(surface.outputs[0],output.inputs[0])
    return material

white=emission('CG coverage',(1,1,1));black=emission('Real environment occlusion',(0,0,0))
for obj in scene.objects:
    if obj.type not in ('MESH','CURVE','SURFACE','FONT','META'):continue
    material=black if obj.is_shadow_catcher else white
    obj.is_shadow_catcher=False
    obj.data.materials.clear();obj.data.materials.append(material)
for frame in range(scene.frame_start,scene.frame_end+1):
    target=args.out/f'{frame-scene.frame_start:05d}.png'
    if target.exists():continue
    scene.frame_set(frame);scene.render.filepath=str(target)
    bpy.ops.render.render(write_still=True)
