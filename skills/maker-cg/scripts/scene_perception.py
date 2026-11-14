"""Infer visible relative depth locally and back-project the photographed scene."""
import argparse
import json
from pathlib import Path

import cv2
import numpy as np
from PIL import Image


def reconstruct(job,model_path):
    import torch
    from transformers import AutoImageProcessor,AutoModelForDepthEstimation

    camera=json.loads((job/'camera.json').read_text(encoding='utf-8'))
    frame=Image.open(job/'plate/00000.png').convert('RGB')
    width,height=frame.size
    torch.set_num_threads(8)
    processor=AutoImageProcessor.from_pretrained(str(model_path),local_files_only=True)
    model=AutoModelForDepthEstimation.from_pretrained(str(model_path),local_files_only=True)
    model.eval()
    inputs=processor(images=frame,return_tensors='pt')
    with torch.inference_mode():
        prediction=model(**inputs).predicted_depth
        depth=torch.nn.functional.interpolate(prediction[:,None],size=(height,width),mode='bicubic',align_corners=False)[0,0].numpy()
    low,high=np.percentile(depth,[3,97])
    relative=np.clip((depth-low)/max(high-low,.001),0,1)
    quad=np.asarray(camera['frames'][0].get('quad',[[0,0],[width,0],[width,height],[0,height]]),np.float32)
    mask=np.zeros((height,width),np.uint8)
    cv2.fillConvexPoly(mask,quad.astype(np.int32),255)
    inverse=.20+relative
    anchor=float(np.median(inverse[mask>0]))
    strength=float(camera['plan'].get('reconstruction',{}).get('relief_strength',.12))
    factor=1+strength*(np.clip(anchor/inverse,.5,2.5)-1)
    K=np.asarray(camera['K'],float)
    world=np.asarray(camera['frames'][0]['camera_matrix'],float)
    y,x=np.mgrid[:height,:width]
    directions=np.stack([(x-K[0,2])/K[0,0],-(y-K[1,2])/K[1,1],-np.ones_like(x)],axis=-1)
    rays=directions@world[:3,:3].T
    distance=-world[2,3]/np.where(abs(rays[:,:,2])<1e-5,-1e-5,rays[:,:,2])
    xyz=world[:3,3]+rays*distance[:,:,None]*factor[:,:,None]
    np.savez_compressed(job/'perception.npz',xyz=xyz.astype(np.float32),relative_inverse_depth=relative.astype(np.float32))
    overview=cv2.applyColorMap(np.uint8(relative*255),cv2.COLORMAP_TURBO)
    cv2.imencode('.jpg',overview)[1].tofile(job/'depth-overview.jpg')
    provenance=model_path/'source.json'
    report=dict(method='Depth Anything V2 Small relative inverse depth + source-camera backprojection',
                model=json.loads(provenance.read_text(encoding='utf-8')) if provenance.exists() else str(model_path),
                input=str(job/'plate/00000.png'),output=str(job/'perception.npz'),
                resolution=[width,height],relief_strength=strength,
                geometry='Visible source surfaces only; source pixels define the texture and image silhouettes.',
                scale='Relative depth stabilized against the tracked plane, with an explicit relief scale. No metric-depth claim.')
    (job/'perception.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Visible scene depth and source-camera geometry saved.',flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--job',type=Path,required=True)
    parser.add_argument('--model',type=Path,required=True)
    args=parser.parse_args()
    reconstruct(args.job.resolve(),args.model.resolve())
