"""Local model inference for visible scene geometry, masks and reference clean plates."""
import argparse
import json
from pathlib import Path

import cv2
import numpy as np
from PIL import Image


def write_json(path,data):
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')


def read_image(path):
    return np.asarray(Image.open(path).convert('RGB'))


def resize_depth(depth,size):
    return cv2.resize(depth,size,interpolation=cv2.INTER_LINEAR)


def reconstruct(job,runtime):
    import torch
    from depth_anything_3.api import DepthAnything3
    from camera_geometry import align_to_anchor,backproject,localize_frames

    plan=json.loads((job/'job.json').read_text(encoding='utf-8'))['plan']
    files=sorted((job/'plate').glob('*.png'))
    h,w=read_image(files[0]).shape[:2]
    options=plan.get('reconstruction',{})
    is_still=Path(plan['source']).suffix.lower() in ('.png','.jpg','.jpeg','.webp','.tif','.tiff')
    indices=np.array([0]) if is_still else np.unique(np.linspace(0,len(files)-1,min(len(files),options.get('views',12))).round().astype(int))
    model_path=Path(options.get('multiview_model',runtime['da3_model']))
    model=DepthAnything3.from_pretrained(str(model_path),local_files_only=True).to(runtime.get('device','cuda:0')).eval()
    prediction=model.inference([str(files[i]) for i in indices],process_res=options.get('process_res',504),
                               process_res_method='upper_bound_resize',ref_view_strategy='first')
    ph,pw=prediction.depth.shape[1:]
    intrinsics=prediction.intrinsics.copy()
    intrinsics[:,0,:]*=w/pw;intrinsics[:,1,:]*=h/ph
    # The predicted camera uses OpenCV +X right, +Y down, +Z forward.
    first_depth=resize_depth(prediction.depth[0],(w,h))
    world=backproject(first_depth,intrinsics[0],prediction.extrinsics[0])
    transform,plane_height=align_to_anchor(world,plan)
    world=world@transform[:3,:3].T+transform[:3,3]
    cameras=[]
    change=np.diag([1,-1,-1,1.])
    for ext in prediction.extrinsics:
        matrix=np.eye(4);matrix[:3,:]=np.asarray(ext)[:3,:]
        camera=transform@np.linalg.inv(matrix)@change
        camera[:3,:3]/=np.cbrt(np.linalg.det(camera[:3,:3]))
        cameras.append(camera)
    # Keep original per-view estimates, then verify/refine every frame against real correspondences.
    np.savez_compressed(job/'multiview-prediction.npz',depth=prediction.depth,
                        conf=prediction.conf,extrinsics=prediction.extrinsics,intrinsics=intrinsics,
                        indices=indices,anchor_transform=transform)
    K=intrinsics[0]
    samples,checks=localize_frames(files,world,K,cameras[0],plan,job)
    quad=plan.get('plane',{}).get('corners')
    if quad:
        for row in samples:
            if row['frame']==0:row['quad']=(np.asarray(quad)*[w,h]).tolist()
    result=dict(width=w,height=h,fps=int(plan.get('fps',24)),count=len(files),K=K.tolist(),
                plane_height=plane_height,frames=samples,plan=plan,
                method=('Depth Anything 3 single-view geometry prior' if is_still else 'Depth Anything 3 multiview visible geometry')+' + SIFT 3D/2D PnP verification',
                intrinsics='Learned intrinsics, no metric calibration; 3D/2D correspondences checked per frame.')
    write_json(job/'camera.json',result)
    confidence=resize_depth(prediction.conf[0],(w,h)) if prediction.conf is not None else np.ones((h,w))
    np.savez_compressed(job/'perception.npz',xyz=world.astype(np.float32),confidence=confidence,
                        depth=first_depth.astype(np.float32))
    norm=np.clip((first_depth-np.percentile(first_depth,3))/max(np.percentile(first_depth,97)-np.percentile(first_depth,3),.001),0,1)
    Image.fromarray(cv2.cvtColor(cv2.applyColorMap(np.uint8(norm*255),cv2.COLORMAP_TURBO),cv2.COLOR_BGR2RGB)).save(job/'depth-overview.jpg')
    source=model_path/'source.json'
    write_json(job/'perception.json',dict(method=('Single-view depth prior' if is_still else 'Joint multiview depth and camera prediction')+' with observed feature validation',
        model=json.loads(source.read_text(encoding='utf-8')) if source.exists() else str(model_path),
        views=indices.tolist(),geometry='Visible surfaces inferred from supplied views; hidden surfaces and physical scale remain unmeasured.',
        camera_checks=checks,world_coordinates='Anchor-aligned Blender world, relative scale'))
    print('Reconstructed visible scene and localized every frame.',flush=True)


def segment(job,runtime):
    import torch
    from sam2.build_sam import build_sam2_video_predictor

    camera=json.loads((job/'camera.json').read_text(encoding='utf-8'))
    spec=camera['plan']['segmentation']
    files=sorted((job/'plate').glob('*.png'))
    frames=job/'sam-input';frames.mkdir(exist_ok=True)
    for n,file in enumerate(files):
        target=frames/f'{n:05d}.jpg'
        if not target.exists():Image.open(file).convert('RGB').save(target,quality=96)
    predictor=build_sam2_video_predictor('configs/sam2.1/sam2.1_hiera_t.yaml',
        runtime['sam2_checkpoint'],device=runtime.get('device','cuda:0'),apply_postprocessing=False)
    destination=job/'masks';destination.mkdir(exist_ok=True)
    w,h=camera['width'],camera['height']
    objects={int(row['id']):row for row in spec['objects']}
    if any(row.get('frame',0)!=0 for row in objects.values()):
        raise ValueError('Initialize tracked objects on frame zero; use a new shot for a later first appearance.')
    records={str(i):[] for i in objects}
    with torch.inference_mode(),torch.autocast('cuda',dtype=torch.bfloat16):
        state=predictor.init_state(str(frames),offload_video_to_cpu=True,offload_state_to_cpu=True)
        for identity,row in objects.items():
            points=np.asarray(row.get('points',[]),np.float32)*[w,h]
            labels=np.asarray(row.get('labels',[1]*len(points)),np.int32)
            box=np.asarray(row['box'],np.float32)*[w,h,w,h] if row.get('box') else None
            predictor.add_new_points_or_box(state,frame_idx=0,obj_id=identity,points=points if len(points) else None,
                                           labels=labels if len(points) else None,box=box)
        for n,ids,logits in predictor.propagate_in_video(state):
            union=np.zeros((h,w),np.uint8)
            for i,identity in enumerate(ids):
                row=objects[int(identity)]
                mask=(logits[i,0].float().cpu().numpy()>0).astype(np.uint8)*255
                object_dir=destination/str(identity);object_dir.mkdir(exist_ok=True)
                Image.fromarray(mask).save(object_dir/f'{n:05d}.png')
                records[str(identity)].append(dict(frame=n,area_fraction=float((mask>0).mean())))
                if row.get('role')=='foreground':union=np.maximum(union,mask)
            foreground=destination/'foreground';foreground.mkdir(exist_ok=True)
            Image.fromarray(union).save(foreground/f'{n:05d}.png')
            if n%24==0:print(f'Tracked object masks {n+1}/{len(files)}',flush=True)
    warnings=[]
    for identity,rows in records.items():
        areas=np.asarray([r['area_fraction'] for r in rows])
        for i in range(len(areas)):
            if areas[i]<.00005 or (i and abs(areas[i]-areas[i-1])>max(.025,areas[i-1]*.45)):
                warnings.append(dict(object=identity,frame=i,reason='Empty or abrupt mask-area change; review actual motion/occlusion.'))
    write_json(job/'segmentation.json',dict(method='SAM 2.1 Tiny video memory propagation',objects=objects,
        frames=len(files),samples=records,review_frames=warnings,foreground=any(o.get('role')=='foreground' for o in objects.values())))
    canvas=read_image(files[0]).copy()
    for identity in objects:
        m=np.asarray(Image.open(destination/str(identity)/'00000.png'))>0
        objects[identity]['observed_material_rgb']=(np.median(read_image(files[0])[m],axis=0)/255).tolist()
        canvas[m]=(.55*canvas[m]+.45*np.array([60,215,175])).astype(np.uint8)
    Image.fromarray(canvas).save(job/'segmentation-overview.jpg')
    write_json(job/'segmentation.json',dict(method='SAM 2.1 Tiny video memory propagation',objects=objects,
        frames=len(files),samples=records,review_frames=warnings,foreground=any(o.get('role')=='foreground' for o in objects.values())))


def clean(job,runtime):
    import torch
    camera=json.loads((job/'camera.json').read_text(encoding='utf-8'))
    spec=camera['plan']['clean_plate']
    frame=read_image(job/'plate/00000.png')
    mask=np.asarray(Image.open(job/'masks'/str(spec['object_id'])/'00000.png').convert('L'))
    radius=int(spec.get('dilate_pixels',5))
    mask=cv2.dilate(mask,np.ones((2*radius+1,2*radius+1),np.uint8))
    if spec.get('reference'):
        replacement=read_image(Path(spec['reference']))
        ys,xs=np.where(mask>0)
        x0,x1=xs.min(),xs.max()+1;y0,y1=ys.min(),ys.max()+1
        clean_frame=frame.copy()
        fitted=cv2.resize(replacement,(x1-x0,y1-y0),interpolation=cv2.INTER_LANCZOS4)
        selection=mask[y0:y1,x0:x1]>0
        clean_frame[y0:y1,x0:x1][selection]=fitted[selection]
        Image.fromarray(clean_frame).save(job/'clean-reference.png')
        write_json(job/'clean-plate.json',dict(method='Observed reference fitted to the target silhouette',
            object_id=spec['object_id'],reference=spec['reference'],output='clean-reference.png',
            review='Single-view reference projected behind the edited surface; perspective and unseen geometry require visual review.'))
        return
    device=runtime.get('device','cuda:0')
    # Passing a file object avoids TorchScript's narrow-character fopen on Windows.
    with Path(runtime['lama_model']).open('rb') as weights:
        model=torch.jit.load(weights,map_location=device).eval()
    h,w=mask.shape
    scale=min(1,1024/max(h,w));sw,sh=round(w*scale),round(h*scale)
    rgb=cv2.resize(frame,(sw,sh));m=cv2.resize(mask,(sw,sh),interpolation=cv2.INTER_NEAREST)
    py=(-sh)%8;px=(-sw)%8
    rgb=np.pad(rgb,((0,py),(0,px),(0,0)),mode='reflect')
    m=np.pad(m,((0,py),(0,px)),mode='constant')
    with torch.inference_mode():
        image=torch.from_numpy(rgb.transpose(2,0,1).copy()).float()[None].to(device)/255
        region=torch.from_numpy((m>0).astype(np.float32))[None,None].to(device)
        result=model(image,region)[0,:,:sh,:sw].permute(1,2,0).cpu().numpy()
    result=cv2.resize(np.uint8(np.clip(result*255,0,255)),(w,h))
    result[mask==0]=frame[mask==0]
    Image.fromarray(result).save(job/'clean-reference.png')
    write_json(job/'clean-plate.json',dict(method='LaMa single-reference inpainting',object_id=spec['object_id'],
        input_frame=0,output='clean-reference.png',review='Generated hidden appearance; inspect visually. This is not factual recovery of an unseen background.'))


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('action',choices=['reconstruct','segment','clean'])
    parser.add_argument('--job',type=Path,required=True)
    parser.add_argument('--runtime',type=Path,required=True)
    args=parser.parse_args()
    runtime=json.loads(args.runtime.read_text(encoding='utf-8-sig'))
    globals()[args.action](args.job.resolve(),runtime)


if __name__=='__main__':main()
