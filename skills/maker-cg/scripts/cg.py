"""Local real-footage CG: measured plane tracking, camera poses and Blender geometry."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import cv2
import numpy as np

SCRIPT = Path(__file__).resolve().parent


def write_json(file, value):
    temp = file.with_suffix('.partial.json')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temp.replace(file)


def read_json(file):
    return json.loads(file.read_text(encoding='utf-8-sig'))


def discover(name):
    local=SCRIPT.parent/'runtime.local.json'
    if local.is_file():
        configured=read_json(local).get(name)
        if configured and Path(configured).is_file():
            return Path(configured)
    found = shutil.which(name)
    if found:
        return Path(found)
    if name == 'blender':
        locations = sorted(Path('C:/Program Files/Blender Foundation').glob('Blender */blender.exe'))
        if locations:
            return locations[-1]
    for parent in [Path.cwd(), *SCRIPT.parents]:
        candidate = parent / '.runtime/ffmpeg/win32' / (name + '.exe')
        if candidate.is_file():
            return candidate
    raise ValueError(f'{name} is missing. Supply --{name} or add it to PATH.')


def call(args, *, log=None, env=None):
    if log:
        with log.open('w', encoding='utf-8') as stream:
            subprocess.run(list(map(str, args)), stdout=stream, stderr=subprocess.STDOUT, check=True,env=env)
    else:
        subprocess.run(list(map(str, args)), check=True,env=env)


def image(file):
    result = cv2.imdecode(np.fromfile(file, dtype=np.uint8), cv2.IMREAD_COLOR)
    if result is None:
        raise ValueError(f'Cannot decode {file}')
    return result


def save_image(file, frame):
    ok, encoded = cv2.imencode(file.suffix, frame)
    if not ok:
        raise ValueError(f'Cannot encode {file}')
    encoded.tofile(file)


@contextmanager
def job(plan_file, out):
    plan = read_json(plan_file)
    base = plan_file.parent
    for key in ('source', 'music'):
        value = Path(plan[key]).expanduser()
        plan[key] = str((base/value).resolve())
        if not Path(plan[key]).is_file():
            raise ValueError(f'Missing {key}: {plan[key]}')
    if plan.get('color', {}).get('status') != 'normalized_sdr':
        raise ValueError('Provide a technically normalized SDR plate and record its color evidence.')
    plan.setdefault('effect', {})
    custom = plan.get('scene_script')
    if custom:
        script = (base/Path(custom)).resolve()
        if not script.is_file() or script.suffix.lower() != '.py':
            raise ValueError('scene_script must reference a local reviewed Blender Python file.')
        plan['scene_script'] = str(script)
    if not custom and plan['effect'].get('preset') not in ('voxel-bloom', 'voxel-scatter', 'portal'):
        raise ValueError('Unknown effect preset')
    if not 0 < float(plan['duration']) <= 30 or not 12 <= int(plan.get('fps', 24)) <= 60:
        raise ValueError('Short single shots only: 0–30 seconds at 12–60 fps')
    if plan['effect'].get('blend_envelope') is not None:
        envelope=np.asarray(plan['effect']['blend_envelope'],dtype=float)
        if (envelope.ndim!=2 or envelope.shape[1]!=2 or len(envelope)<2 or
            not np.isfinite(envelope).all() or np.any(np.diff(envelope[:,0])<=0) or
            envelope[0,0]<0 or envelope[-1,0]>float(plan['duration']) or
            np.any((envelope[:,1]<0)|(envelope[:,1]>1))):
            raise ValueError('blend_envelope must contain increasing [seconds, opacity] pairs, with opacity in 0–1.')
    mode = plan.get('camera', {}).get('mode', 'planar')
    if mode not in ('planar', 'fixed', 'imported', 'reconstructed'):
        raise ValueError('Camera mode must be planar, fixed, imported or reconstructed.')
    if mode == 'planar':
        corners = np.asarray(plan.get('plane', {}).get('corners'), dtype=float)
        if corners.shape != (4, 2) or not np.isfinite(corners).all() or np.any((corners < 0) | (corners > 1)):
            raise ValueError('Four normalized plane corners are required in TL, TR, BR, BL order.')
        contour = corners.astype(np.float32)
        if not cv2.isContourConvex(contour) or cv2.contourArea(contour) < .002:
            raise ValueError('Select a visible convex plane with enough area to track.')
    if not .2 <= float(plan.get('plane', {}).get('aspect', 1)) <= 5:
        raise ValueError('Plane aspect must be a positive width/height ratio between 0.2 and 5.')
    if not 320 <= int(plan.get('width', 1280)) <= 3840:
        raise ValueError('Output width must be between 320 and 3840.')
    # Preserve a private source fingerprint without copying its content into a skill.
    assets = plan.get('assets', {})
    if not isinstance(assets, dict):
        raise ValueError('assets must map asset names to local model or texture paths.')
    for name, value in list(assets.items()):
        asset = (base/Path(value)).resolve()
        if not asset.is_file():
            raise ValueError(f'Missing scene asset: {asset}')
        assets[name] = str(asset)
    if mode == 'imported':
        camera = (base/Path(plan['camera']['file'])).resolve()
        if not camera.is_file():
            raise ValueError('Missing solved camera JSON.')
        plan['camera']['file'] = str(camera)
    if plan.get('foreground_mask'):
        foreground = (base/Path(plan['foreground_mask'])).resolve()
        if not foreground.is_file():
            raise ValueError('Missing foreground mask. White must identify protected real foreground.')
        plan['foreground_mask'] = str(foreground)
    if plan.get('clean_plate',{}).get('reference'):
        reference=(base/Path(plan['clean_plate']['reference'])).resolve()
        if not reference.is_file():raise ValueError('Missing observed clean-plate reference.')
        plan['clean_plate']['reference']=str(reference)
    reconstruction=plan.get('reconstruction',{})
    if reconstruction.get('depth_model'):
        model=(base/Path(reconstruction['depth_model'])).resolve()
        if not (model/'model.safetensors').is_file():
            raise ValueError('The configured local depth model is missing.')
        reconstruction['depth_model']=str(model)
    source = Path(plan['source'])
    identity = dict(plan=plan, source_size=source.stat().st_size, source_mtime=source.stat().st_mtime_ns,
                    adapter=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                    renderer=hashlib.sha256((SCRIPT/'blender_scene.py').read_bytes()).hexdigest())
    dependencies = list(assets.values()) + ([plan['scene_script']] if custom else [])
    if mode == 'imported':
        dependencies.append(plan['camera']['file'])
    if plan.get('foreground_mask'):
        dependencies.append(plan['foreground_mask'])
    if plan.get('clean_plate',{}).get('reference'):
        dependencies.append(plan['clean_plate']['reference'])
    identity['dependencies'] = {value:hashlib.sha256(Path(value).read_bytes()).hexdigest() for value in dependencies}
    identity['scene_helpers']={f.name:hashlib.sha256(f.read_bytes()).hexdigest() for f in SCRIPT.glob('*.py')}
    if mode=='reconstructed' or plan.get('segmentation') or plan.get('clean_plate'):
        from cg_runtime import configuration
        runtime=configuration()
        identity['scene_runtime']=runtime
        identity['local_models']={}
        for key in ('da3_model','sam2_checkpoint','lama_model'):
            if not runtime.get(key):continue
            file=Path(runtime[key]);file=file/'model.safetensors' if file.is_dir() else file
            if file.is_file():identity['local_models'][key]=[file.stat().st_size,file.stat().st_mtime_ns]
    if plan.get('segmentation'):
        objects=plan['segmentation'].get('objects',[])
        if not objects or len({row['id'] for row in objects})!=len(objects):
            raise ValueError('Segmentation needs unique object IDs and image-grounded prompts.')
        for row in objects:
            if not row.get('points') and not row.get('box'):
                raise ValueError('Each segmented object needs observed image points or a box.')
            if row.get('role','target') not in ('target','foreground'):
                raise ValueError('Segmented objects use target or foreground roles.')
    signature = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    marker = out/'job.json'
    if out.exists() and any(out.iterdir()) and not marker.exists():
        raise ValueError('Output folder has unrelated content. Choose a new version directory.')
    out.mkdir(parents=True, exist_ok=True)
    lock = out/'.running'
    with lock.open('x', encoding='ascii') as stream:
        stream.write(str(os.getpid()))
    try:
        if marker.exists() and read_json(marker)['signature'] != signature:
            raise ValueError('Plan, source or code changed. Choose a new output version directory.')
        if not marker.exists():
            write_json(marker, dict(signature=signature, plan=plan, status='prepared_for_execution'))
        yield plan
    finally:
        lock.unlink(missing_ok=True)


def prepare(plan, out, ffmpeg):
    if (out/'camera.json').exists():
        return read_json(out/'camera.json')
    fps = int(plan.get('fps', 24))
    count = round(plan['duration']*fps)
    width = int(plan.get('width', 1280))
    if width % 2:
        raise ValueError('Output width must be even.')
    plates = out/'plate'
    plates.mkdir(exist_ok=True)
    print('Extracting normalized single-shot frames', flush=True)
    is_image=Path(plan['source']).suffix.lower() in ('.png','.jpg','.jpeg','.webp','.tif','.tiff')
    inputs=['-loop','1','-framerate',fps] if is_image else ['-ss',plan.get('start',0)]
    call([ffmpeg, '-v', 'error', '-nostdin', '-y', *inputs, '-i', plan['source'],
          '-an', '-vf', f'fps={fps},scale={width}:-2:flags=lanczos,format=rgb24',
          '-frames:v', count, '-start_number', '0', plates/'%05d.png'])
    frames = sorted(plates.glob('*.png'))
    if len(frames) != count:
        raise ValueError('Source ends before the requested shot ends.')
    reference = image(frames[0])
    height, width = reference.shape[:2]
    mode = plan.get('camera', {}).get('mode', 'planar')
    if mode=='reconstructed':
        from cg_runtime import worker
        worker('reconstruct',out,log=out/'reconstruction.log')
        return read_json(out/'camera.json')
    if mode != 'planar':
        stationary = check_fixed_camera(reference, frames, plan['camera'].get('reference_region')) if mode == 'fixed' else None
        result = supplied_camera(plan, width, height, fps, count)
        result['fixed_camera_check'] = stationary
        write_json(out/'camera.json', result)
        return result
    quad = np.asarray(plan['plane']['corners'], np.float32)*[width, height]
    quad = quad.astype(np.float32)
    mask = np.zeros((height, width), np.uint8)
    cv2.fillConvexPoly(mask, quad.astype(np.int32), 255)
    gray0 = cv2.cvtColor(reference, cv2.COLOR_BGR2GRAY)
    sift = cv2.SIFT_create(nfeatures=3500, contrastThreshold=.013, edgeThreshold=14)
    features, descriptors = sift.detectAndCompute(gray0, mask)
    if descriptors is None or len(features) < 24:
        raise ValueError('The selected plane has too little texture for reliable tracking.')
    matcher = cv2.BFMatcher(cv2.NORM_L2)
    aspect = float(plan['plane'].get('aspect', 1))
    physical_height = 1/aspect
    world = np.array([[-.5, physical_height/2, 0], [.5, physical_height/2, 0],
                      [.5, -physical_height/2, 0], [-.5, -physical_height/2, 0]], np.float64)
    focal = width*float(plan['plane'].get('focal_width_ratio', 1.05))
    K = np.array([[focal, 0, width/2], [0, focal, height/2], [0, 0, 1]], float)
    previous = np.eye(3)
    rvec = tvec = None
    samples = []
    uv_to_first = cv2.getPerspectiveTransform(np.float32([[0,0],[1,0],[1,1],[0,1]]), quad)
    for n, file in enumerate(frames):
        frame = image(file)
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        predicted = cv2.perspectiveTransform(quad[None], previous)[0]
        search = np.zeros_like(mask)
        cv2.fillConvexPoly(search, predicted.astype(np.int32), 255)
        search = cv2.dilate(search, np.ones((61,61),np.uint8))
        current, current_descriptors = sift.detectAndCompute(gray, search)
        if current_descriptors is None:
            raise ValueError(f'Tracking lost at frame {n}')
        matches = matcher.knnMatch(descriptors, current_descriptors, k=2)
        good = [a for pair in matches if len(pair)==2 for a,b in [pair] if a.distance < .73*b.distance]
        if len(good) < 16:
            raise ValueError(f'Insufficient correspondences at frame {n}: {len(good)}')
        a = np.float32([features[m.queryIdx].pt for m in good])
        b = np.float32([current[m.trainIdx].pt for m in good])
        H, inlier = cv2.findHomography(a, b, cv2.USAC_MAGSAC, 2.2, maxIters=4000, confidence=.999)
        if H is None:
            raise ValueError(f'Plane estimation failed at frame {n}')
        selected = inlier.ravel().astype(bool)
        inliers = int(selected.sum())
        residual = float(np.median(np.linalg.norm(cv2.perspectiveTransform(a[selected][None], H)[0]-b[selected], axis=1)))
        if inliers < 14 or inliers/len(good) < .46 or residual > 1.5:
            raise ValueError(f'Unreliable track at frame {n}: {inliers} inliers, {residual:.2f}px')
        observed = cv2.perspectiveTransform(quad[None], H)[0].astype(np.float64)
        if rvec is None:
            ok, rvec, tvec = cv2.solvePnP(world, observed, K, None, flags=cv2.SOLVEPNP_ITERATIVE)
        else:
            ok, rvec, tvec = cv2.solvePnP(world, observed, K, None, rvec, tvec, True, flags=cv2.SOLVEPNP_ITERATIVE)
        if not ok or float(tvec[2,0]) <= 0:
            raise ValueError(f'Camera pose failed at frame {n}')
        projected = cv2.projectPoints(world, rvec, tvec, K, None)[0].reshape(-1,2)
        reprojection = float(np.sqrt(np.mean(np.sum((projected-observed)**2, axis=1))))
        if reprojection > 5:
            raise ValueError(f'Inconsistent camera model at frame {n}: {reprojection:.2f}px')
        R = cv2.Rodrigues(rvec)[0]
        cv_world = np.eye(4)
        cv_world[:3,:3] = R
        cv_world[:3,3] = tvec[:,0]
        camera_matrix = np.linalg.inv(cv_world) @ np.diag([1,-1,-1,1])
        samples.append(dict(frame=n, camera_matrix=camera_matrix.tolist(), quad=observed.tolist(),
                            inliers=inliers, matches=len(good), median_match_error_px=round(residual,4),
                            corner_reprojection_rms_px=round(reprojection,4)))
        previous = H
        if n in (0, count//3, 2*count//3, count-1):
            check=frame.copy()
            cv2.polylines(check,[observed.astype(np.int32)],True,(50,230,220),2,cv2.LINE_AA)
            for pt in b[selected][::max(1,inliers//45)]:cv2.circle(check,tuple(pt.astype(int)),2,(40,255,70),-1)
            save_image(out/f'track-{n:05d}.jpg',check)
        if n%30==0:print(f'Tracked {n+1}/{count}, {inliers} inliers, {residual:.2f}px median error',flush=True)
    # Sample the photographed face for the voxel skin; these are source pixels, never generated detail.
    palette=[]
    sample_region = plan['effect'].get('sample_region', [.2,.3,.8,.7])
    u0,v0,u1,v1 = sample_region
    if not (0 <= u0 < u1 <= 1 and 0 <= v0 < v1 <= 1):
        raise ValueError('effect.sample_region must be a normalized rectangle inside the selected plane.')
    for row in range(7):
        for col in range(13):
            u=u0+col*(u1-u0)/12
            v=v0+row*(v1-v0)/6
            at=cv2.perspectiveTransform(np.float32([[[u,v]]]),uv_to_first)[0,0]
            x,y=np.rint(at).astype(int)
            rgb=reference[max(0,y-2):y+3,max(0,x-2):x+3,::-1].mean(axis=(0,1))/255
            palette.append(rgb.tolist())
    result=dict(width=width,height=height,fps=fps,count=count,K=K.tolist(),plane_height=physical_height,
                method='SIFT + MAGSAC planar homography, iterative solvePnP camera poses',
                intrinsics='approximate focal length, zero distortion; not a calibrated full-scene reconstruction',
                frames=samples,palette=palette,plan=plan)
    write_json(out/'camera.json',result)
    return result


def supplied_camera(plan, width, height, fps, count):
    camera = plan['camera']
    mode = camera['mode']
    if mode == 'imported':
        data = read_json(Path(camera['file']))
        if (data['width'], data['height'], data['fps'], len(data['frames'])) != (width,height,fps,count):
            raise ValueError('Imported camera resolution, frame rate and frame count must match the extracted plate.')
        for index,row in enumerate(data['frames']):
            matrix = np.asarray(row['camera_matrix'],dtype=float)
            if row['frame'] != index or matrix.shape != (4,4) or not np.isfinite(matrix).all():
                raise ValueError(f'Invalid imported camera frame {index}')
            rotation=matrix[:3,:3]
            if not np.allclose(matrix[3], [0,0,0,1]) or not np.isclose(np.linalg.det(rotation),1,atol=1e-3) or not np.allclose(rotation.T@rotation,np.eye(3),atol=1e-3):
                raise ValueError(f'Imported camera is not a rigid Blender camera transform at frame {index}')
        method = 'Imported Blender-convention camera poses'
        intrinsics = data.get('intrinsics','Imported camera. Calibration quality follows the supplying solver.')
        K = data['K']
        matrix = np.asarray(K,dtype=float)
        if matrix.shape != (3,3) or not np.isfinite(matrix).all() or min(matrix[0,0],matrix[1,1])<=0:
            raise ValueError('Invalid imported intrinsic matrix.')
        if not np.isclose(matrix[0,0],matrix[1,1],rtol=.001) or matrix[0,1] != 0 or not np.allclose(matrix[2],[0,0,1]):
            raise ValueError('Imported camera must use zero skew and square pixels. Undistort the plate first.')
        frames = data['frames']
    else:
        focal=width*float(camera.get('focal_width_ratio',1.05))
        distance=float(camera.get('distance',3))
        if not np.isfinite([focal,distance]).all() or min(focal,distance)<=0:
            raise ValueError('Fixed camera focal length and distance must be positive and finite.')
        K=[[focal,0,width/2],[0,focal,height/2],[0,0,1]]
        matrix=np.eye(4)
        matrix[2,3]=distance
        frames=[dict(frame=i,camera_matrix=matrix.tolist()) for i in range(count)]
        method='Explicit fixed camera'
        intrinsics='User/Agent selected stationary-camera setup with approximate focal length.'
    return dict(width=width,height=height,fps=fps,count=count,K=K,frames=frames,method=method,
                intrinsics=intrinsics,plane_height=1/float(plan.get('plane',{}).get('aspect',1)),
                palette=[[.22,.63,.36]]*91,plan=plan)


def check_fixed_camera(reference, frames, region=None):
    detector=cv2.SIFT_create(nfeatures=2400)
    height,width=reference.shape[:2]
    mask=None
    if region:
        x0,y0,x1,y1=region
        if not 0<=x0<x1<=1 or not 0<=y0<y1<=1:
            raise ValueError('camera.reference_region must be a normalized background rectangle.')
        mask=np.zeros((height,width),dtype=np.uint8)
        mask[round(y0*height):round(y1*height),round(x0*width):round(x1*width)]=255
    features,desc=detector.detectAndCompute(cv2.cvtColor(reference,cv2.COLOR_BGR2GRAY),mask)
    if desc is None:
        raise ValueError('Cannot verify fixed camera on a textureless shot.')
    corners=np.float32([[[0,0],[width,0],[width,height],[0,height]]])
    checks=[]
    for index in sorted({len(frames)//4,len(frames)//2,3*len(frames)//4,len(frames)-1}):
        now=image(frames[index])
        current,other=detector.detectAndCompute(cv2.cvtColor(now,cv2.COLOR_BGR2GRAY),mask)
        if other is None:
            raise ValueError('Fixed-camera verification failed. Inspect for a cut or camera motion.')
        pairs=cv2.BFMatcher().knnMatch(desc,other,k=2)
        matches=[a for pair in pairs if len(pair)==2 for a,b in [pair] if a.distance<.70*b.distance]
        if len(matches)<20:
            raise ValueError('Fixed-camera verification found a possible cut or major motion.')
        a=np.float32([features[m.queryIdx].pt for m in matches])
        b=np.float32([current[m.trainIdx].pt for m in matches])
        homography,inliers=cv2.findHomography(a,b,cv2.USAC_MAGSAC,1.5)
        if homography is None or int(inliers.sum())<20:
            raise ValueError('Cannot establish a stationary background for fixed-camera mode.')
        displacement=float(np.linalg.norm(cv2.perspectiveTransform(corners,homography)-corners,axis=2).max())
        if displacement>width*.005:
            raise ValueError(f'Camera moves at frame {index} ({displacement:.1f}px). Select planar tracking or import a solved camera.')
        checks.append(dict(frame=index,maximum_background_displacement_px=round(displacement,3)))
    return checks


def render(plan, out, blender, still=None):
    command=[blender,'--background','--factory-startup','--python-exit-code','1','--python',SCRIPT/'blender_scene.py','--','--job',out]
    if still is not None:
        command += ['--still',still]
    print('Rendering native Blender geometry', flush=True)
    environment=os.environ.copy()
    for parent in [out,*out.parents]:
        if (parent/'.runtime').is_dir():
            cache=parent/'.runtime/cg-optix-cache';cache.mkdir(exist_ok=True)
            environment['OPTIX_CACHE_PATH']=str(cache)
            break
    call(command,log=out/('blender-still.log' if still is not None else 'blender.log'),env=environment)


def finish(plan, out, ffmpeg, ffprobe):
    camera=read_json(out/'camera.json')
    frames=sorted((out/'cg').glob('*.png'))
    if len(frames)!=camera['count']:
        raise ValueError(f'Incomplete CG image sequence: {len(frames)}/{camera["count"]}')
    fps=camera['fps']
    merged=out/'composite'
    merged.mkdir(exist_ok=True)
    mask_frames=[]
    if plan.get('foreground_mask'):
        masks=out/'foreground'
        masks.mkdir(exist_ok=True)
        mask_file=Path(plan['foreground_mask'])
        still=mask_file.suffix.lower() in ('.png','.jpg','.jpeg','.webp')
        inputs=['-loop','1'] if still else []
        call([ffmpeg,'-v','error','-nostdin','-y',*inputs,'-i',mask_file,'-an','-vf',
              f'fps={fps},scale={camera["width"]}:{camera["height"]},format=gray',
              '-frames:v',camera['count'],'-start_number','0',masks/'%05d.png'])
        mask_frames=sorted(masks.glob('*.png'))
        if len(mask_frames)!=camera['count']:
            raise ValueError('Foreground mask does not cover the whole shot.')
    elif (out/'segmentation.json').exists() and read_json(out/'segmentation.json').get('foreground'):
        mask_frames=sorted((out/'masks/foreground').glob('*.png'))
        if len(mask_frames)!=camera['count']:raise ValueError('Tracked foreground masks are incomplete.')
    from PIL import Image
    from compositing import Compositor
    compositor=Compositor(plan,out,camera,mask_frames or None)
    envelope=plan['effect'].get('blend_envelope')
    for n in range(camera['count']):
        Image.fromarray(compositor.frame(n)).save(merged/f'{n:05d}.png')
    video=out/'CG-effect.mp4'
    music=f'loudnorm=I=-18:TP=-1.8:LRA=7,afade=t=in:d=0.4,afade=t=out:st={camera["count"]/fps-.7}:d=0.7'
    source_info=json.loads(subprocess.check_output([str(ffprobe),'-v','error','-show_streams','-of','json',plan['source']]))
    preserve=plan.get('audio',{}).get('original','preserve')=='preserve' and any(s['codec_type']=='audio' for s in source_info['streams'])
    inputs=['-framerate',fps,'-i',merged/'%05d.png','-ss',plan.get('music_offset',0),'-i',plan['music']]
    if preserve:
        inputs+=['-ss',plan.get('start',0),'-i',plan['source']]
        audio_graph=(f'[1:a]{music},aresample=48000,aformat=channel_layouts=stereo[bed];'
                     '[2:a]aresample=48000,aformat=channel_layouts=stereo,asplit[side][voice];'
                     '[bed][side]sidechaincompress=threshold=0.025:ratio=4:attack=20:release=280[ducked];'
                     '[ducked][voice]amix=inputs=2:duration=longest:normalize=0,alimiter=limit=0.94[a]')
        audio_args=['-filter_complex',audio_graph,'-map','[a]']
    else:
        audio_args=['-map','1:a','-af',music]
    call([ffmpeg,'-v','error','-nostdin','-y',*inputs,'-map','0:v',*audio_args,
          '-frames:v',camera['count'],'-t',camera['count']/fps,
          '-vf','scale=in_range=pc:out_range=tv:out_color_matrix=bt709,format=yuv420p',
          '-c:v','libx264','-preset','fast','-crf','16','-g',fps*2,
          '-color_range','tv','-colorspace','bt709','-color_trc','bt709','-color_primaries','bt709',
          '-c:a','aac','-b:a','224k','-movflags','+faststart',video])
    comparison=out/'CG-before-after.mp4'
    fit='scale=960:540:force_original_aspect_ratio=decrease,pad=960:540:(ow-iw)/2:(oh-ih)/2'
    call([ffmpeg,'-v','error','-nostdin','-y','-framerate',fps,'-i',out/'plate/%05d.png','-i',video,
          '-filter_complex',f'[0:v]{fit}[a];[1:v]{fit}[b];[a][b]hstack=inputs=2[v]',
          '-map','[v]','-map','1:a','-frames:v',camera['count'],'-c:v','libx264','-preset','fast',
          '-crf','17','-pix_fmt','yuv420p','-c:a','copy','-movflags','+faststart',comparison])
    info=json.loads(subprocess.check_output([str(ffprobe),'-v','error','-show_streams','-of','json',str(video)]))
    v,a=info['streams']
    assert int(v['nb_frames'])==camera['count'] and a['channels']==2
    assert abs(float(v['duration'])-float(a['duration']))<.04
    call([ffmpeg,'-v','error','-xerror','-i',video,'-map','0:v','-map','0:a','-f','null','-'])
    write_json(out/'verification.json',dict(status='rendered_and_machine_checked',video=str(video),comparison=str(comparison),
        frames=camera['count'],resolution=[camera['width'],camera['height']],fps=fps,
        tracking_method=camera['method'],minimum_inliers=min((r['inliers'] for r in camera['frames'] if 'inliers' in r),default=None),
        median_track_error_px=float(np.median([r['median_match_error_px'] for r in camera['frames']])) if 'median_match_error_px' in camera['frames'][0] else None,
        maximum_reprojection_error_px=max((r['corner_reprojection_rms_px'] for r in camera['frames'] if r.get('corner_reprojection_rms_px') is not None),default=None),
        limitations=[camera['intrinsics'],'Visible scene geometry and authored CG; unseen surfaces remain unmeasured.'],
        original_audio_preserved=preserve,foreground_mask_used=bool(mask_frames),
        blend_envelope=envelope,
        audio_review='Pending human listening. The rendered MP4 has the supplied music mixed in.',
        music=dict(file=plan['music'],offset=plan.get('music_offset',0),source=plan.get('music_provenance'))))
    print(f'Created {video}',flush=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ffmpeg',type=Path)
    parser.add_argument('--blender',type=Path)
    commands=parser.add_subparsers(dest='command',required=True)
    commands.add_parser('doctor')
    commands.add_parser('presets')
    inspection=commands.add_parser('inspect')
    inspection.add_argument('source',type=Path)
    inspection.add_argument('--out',type=Path,required=True)
    inspection.add_argument('--start',type=float,default=0)
    inspection.add_argument('--duration',type=float,default=8)
    recomposition=commands.add_parser('recompose')
    recomposition.add_argument('parent',type=Path)
    recomposition.add_argument('--out',type=Path,required=True)
    recomposition.add_argument('--shadow-strength',type=float,required=True)
    for name in ('prepare','render','finish'):
        child=commands.add_parser(name)
        child.add_argument('plan',type=Path)
        child.add_argument('--out',type=Path,required=True)
        if name=='render':child.add_argument('--still',type=int)
    args=parser.parse_args()
    if args.command=='presets':
        print(json.dumps(dict(built_in=['voxel-bloom','voxel-scatter','portal'],
                              custom_scene='scene_script implementing build_scene(context)',
                              models=['GLB','GLTF','OBJ','FBX'],camera_modes=['planar','fixed','imported','reconstructed']),indent=2))
        return
    ffmpeg=args.ffmpeg or discover('ffmpeg')
    ffprobe=ffmpeg.with_name('ffprobe.exe' if ffmpeg.suffix.lower()=='.exe' else 'ffprobe')
    if args.command=='inspect':
        from inspect_scene import inspect
        inspect(args.source,args.out.resolve(),ffmpeg,ffprobe,args.start,args.duration)
        return
    blender=args.blender or discover('blender')
    if args.command=='recompose':
        from recompose_scene import recompose
        recompose(args.parent,args.out,ffmpeg,ffprobe,blender,args.shadow_strength)
        return
    if args.command=='doctor':
        print(json.dumps(dict(opencv=cv2.__version__,ffmpeg=str(ffmpeg),blender=str(blender),
                              presets=['voxel-bloom','voxel-scatter','portal'],custom_scenes=True,
                              camera_modes=['planar','fixed','imported','reconstructed'],foreground_masks=True,
                              scene_runtime=__import__('cg_runtime').configuration()),ensure_ascii=False,indent=2))
        return
    with job(args.plan.resolve(),args.out.resolve()) as plan:
        out=args.out.resolve()
        if args.command=='render' and args.still is not None and not 0 <= args.still < round(plan['duration']*plan.get('fps',24)):
            raise ValueError('--still must be an existing zero-based frame of the planned shot.')
        prepare(plan,out,ffmpeg)
        if plan.get('segmentation') and not (out/'segmentation.json').exists():
            from cg_runtime import worker
            worker('segment',out,log=out/'segmentation.log')
        if plan.get('clean_plate') and not (out/'clean-reference.png').exists():
            from cg_runtime import worker
            worker('clean',out,log=out/'clean-plate.log')
        if plan.get('reconstruction',{}).get('depth_model') and not (out/'perception.npz').exists():
            call([sys.executable,SCRIPT/'scene_perception.py','--job',out,'--model',plan['reconstruction']['depth_model']],log=out/'perception.log')
        if args.command=='render':
            render(plan,out,blender,args.still)
            if args.still is None:finish(plan,out,ffmpeg,ffprobe)
            else:
                from compositing import Compositor
                from PIL import Image
                camera=read_json(out/'camera.json')
                preview=out/f'CG-preview-{args.still:05d}.png'
                Image.fromarray(Compositor(plan,out,camera).frame(args.still)).save(preview)
                print(f'Created composite preview {preview}',flush=True)
        elif args.command=='finish':finish(plan,out,ffmpeg,ffprobe)


if __name__=='__main__':
    for stream in (sys.stdout,sys.stderr):
        if hasattr(stream,'reconfigure'):
            stream.reconfigure(encoding='utf-8',errors='replace')
    try:main()
    except (ValueError,OSError,subprocess.CalledProcessError) as exc:
        print(f'CG error: {exc}',file=sys.stderr)
        raise SystemExit(1)
