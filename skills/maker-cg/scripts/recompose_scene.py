"""Versioned visual recomposition of a finished scene without re-running its models or Cycles."""
import hashlib
import json
from pathlib import Path
import subprocess

from PIL import Image

from compositing import Compositor


def recompose(parent,out,ffmpeg,ffprobe,blender,strength):
    if not 0<=strength<=1:raise ValueError('shadow-strength must be between zero and one.')
    if out.exists() and any(out.iterdir()):raise ValueError('Choose a new recomposition output version.')
    parent=parent.resolve();out=out.resolve()
    camera=json.loads((parent/'camera.json').read_text(encoding='utf-8'))
    previous=json.loads((parent/'verification.json').read_text(encoding='utf-8'))
    plan=camera['plan']
    if len(list((parent/'cg').glob('*.png')))!=camera['count']:raise ValueError('Parent CG render is incomplete.')
    out.mkdir(parents=True,exist_ok=True)
    marker=dict(parent=str(parent),parent_job=json.loads((parent/'job.json').read_text(encoding='utf-8'))['signature'],
                shadow_strength=strength,operation='Object-matte shadow recomposition; parent render remains unchanged.',
                scripts={f.name:hashlib.sha256(f.read_bytes()).hexdigest() for f in Path(__file__).parent.glob('*.py')})
    (out/'postprocess.json').write_text(json.dumps(marker,ensure_ascii=False,indent=2),encoding='utf-8')
    command=[str(blender),'--background',str(parent/'tracked-effect.blend'),'--python-exit-code','1',
             '--python',str(Path(__file__).with_name('blender_object_matte.py')),'--','--out',str(out/'object-matte')]
    with (out/'matte-render.log').open('w',encoding='utf-8') as log:
        subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,check=True)
    foreground=sorted((parent/'foreground').glob('*.png')) or None
    compositor=Compositor(plan,parent,camera,foreground,shadow_folder=out/'object-matte',shadow_strength=strength)
    frames=out/'composite';frames.mkdir(exist_ok=True)
    for n in range(camera['count']):Image.fromarray(compositor.frame(n)).save(frames/f'{n:05d}.png')
    fps=camera['fps'];video=out/'CG-effect.mp4';duration=camera['count']/fps
    command=[str(ffmpeg),'-v','error','-nostdin','-y','-framerate',str(fps),'-i',str(frames/'%05d.png'),
        '-i',str(parent/'CG-effect.mp4'),'-map','0:v','-map','1:a','-frames:v',str(camera['count']),'-t',str(duration),
        '-vf','scale=in_range=pc:out_range=tv:out_color_matrix=bt709,format=yuv420p','-c:v','libx264','-preset','fast','-crf','16',
        '-color_range','tv','-colorspace','bt709','-color_trc','bt709','-color_primaries','bt709',
        '-c:a','copy','-movflags','+faststart',str(video)]
    subprocess.run(command,check=True)
    comparison=out/'CG-before-after.mp4'
    fit='scale=960:540:force_original_aspect_ratio=decrease,pad=960:540:(ow-iw)/2:(oh-ih)/2'
    subprocess.run([str(ffmpeg),'-v','error','-nostdin','-y','-framerate',str(fps),'-i',str(parent/'plate/%05d.png'),'-i',str(video),
        '-filter_complex',f'[0:v]{fit}[a];[1:v]{fit}[b];[a][b]hstack=inputs=2[v]',
        '-map','[v]','-map','1:a','-frames:v',str(camera['count']),'-c:v','libx264','-crf','17','-pix_fmt','yuv420p','-c:a','copy',str(comparison)],check=True)
    info=json.loads(subprocess.check_output([str(ffprobe),'-v','error','-show_streams','-of','json',str(video)]))
    stream=next(s for s in info['streams'] if s['codec_type']=='video')
    assert int(stream['nb_frames'])==camera['count']
    subprocess.run([str(ffmpeg),'-v','error','-xerror','-i',str(video),'-f','null','-'],check=True)
    previous.update(video=str(video),comparison=str(comparison),parent_render=str(parent),shadow_recomposition=strength,
                    audio_review='Original parent MP4 audio copied without re-encoding; subjective listening still pending.')
    (out/'verification.json').write_text(json.dumps(previous,ensure_ascii=False,indent=2),encoding='utf-8')
    print(f'Created shadow-adjusted version {video}',flush=True)
