"""Coordinate conversion and observed 3D/2D camera validation, independent of Blender."""
import cv2
import numpy as np
from PIL import Image


def backproject(depth,K,extrinsic):
    h,w=depth.shape
    y,x=np.mgrid[:h,:w]
    pixels=np.stack([x,y,np.ones_like(x)],axis=-1)
    local=(pixels@np.linalg.inv(K).T)*depth[:,:,None]
    matrix=np.eye(4);matrix[:3,:]=np.asarray(extrinsic)[:3,:]
    inverse=np.linalg.inv(matrix)
    return local@inverse[:3,:3].T+inverse[:3,3]


def align_to_anchor(xyz,plan):
    h,w=xyz.shape[:2]
    corners=plan.get('plane',{}).get('corners',[[.3,.3],[.7,.3],[.7,.7],[.3,.7]])
    points=[]
    for u,v in corners:
        x=int(np.clip(u*w,3,w-4));y=int(np.clip(v*h,3,h-4))
        points.append(np.median(xyz[y-2:y+3,x-2:x+3].reshape(-1,3),axis=0))
    q=np.asarray(points)
    right=(q[1]-q[0])+(q[2]-q[3]);right/=np.linalg.norm(right)
    up=(q[0]-q[3])+(q[1]-q[2]);up-=right*np.dot(up,right);up/=np.linalg.norm(up)
    normal=np.cross(right,up)
    width=np.mean([np.linalg.norm(q[1]-q[0]),np.linalg.norm(q[2]-q[3])])
    if not np.isfinite(width) or width<1e-5:raise ValueError('Scene anchor has no reliable extent.')
    rotation=np.stack([right,up,normal])/width
    transform=np.eye(4);transform[:3,:3]=rotation;transform[:3,3]=-rotation@q.mean(axis=0)
    height=np.mean([np.linalg.norm(q[3]-q[0]),np.linalg.norm(q[2]-q[1])])/width
    return transform,float(height)


def localize_frames(files,xyz,K,first_camera,plan,job):
    first=cv2.cvtColor(np.asarray(Image.open(files[0]).convert('RGB')),cv2.COLOR_RGB2GRAY)
    mask=np.full(first.shape,255,np.uint8)
    for rectangle in plan.get('camera',{}).get('exclude_regions',[]):
        x0,y0,x1,y1=np.asarray(rectangle)*[first.shape[1],first.shape[0],first.shape[1],first.shape[0]]
        mask[int(y0):int(y1),int(x0):int(x1)]=0
    sift=cv2.SIFT_create(nfeatures=5000,contrastThreshold=.015)
    reference,descriptors=sift.detectAndCompute(first,mask)
    if descriptors is None or len(reference)<80:raise ValueError('Too few background features for 3D camera verification.')
    pixels=np.asarray([k.pt for k in reference])
    rounded=np.rint(pixels).astype(int)
    rounded[:,0]=np.clip(rounded[:,0],0,xyz.shape[1]-1)
    rounded[:,1]=np.clip(rounded[:,1],0,xyz.shape[0]-1)
    points=xyz[rounded[:,1],rounded[:,0]]
    initial=np.linalg.inv(first_camera@np.diag([1,-1,-1,1]))
    rvec=cv2.Rodrigues(initial[:3,:3])[0];tvec=initial[:3,3].copy()
    matcher=cv2.BFMatcher(cv2.NORM_L2)
    samples=[]
    for n,file in enumerate(files):
        rgb=np.asarray(Image.open(file).convert('RGB'))
        current,d=sift.detectAndCompute(cv2.cvtColor(rgb,cv2.COLOR_RGB2GRAY),None)
        if d is None:raise ValueError(f'3D localization has no image features at frame {n}.')
        pairs=matcher.knnMatch(descriptors,d,k=2)
        selected=[a for pair in pairs if len(pair)==2 for a,b in [pair] if a.distance<.72*b.distance]
        world=np.asarray([points[m.queryIdx] for m in selected],np.float64)
        target=np.asarray([current[m.trainIdx].pt for m in selected],np.float64)
        valid=np.isfinite(world).all(axis=1) if len(world) else np.zeros(0,bool)
        world=world[valid];target=target[valid]
        if len(world)<35:raise ValueError(f'3D camera lost overlap at frame {n}; select SfM or another shot.')
        ok,rv,tv,inliers=cv2.solvePnPRansac(world,target,K,None,rvec.copy(),tvec.copy(),True,
            iterationsCount=1000,reprojectionError=3.2,confidence=.999,flags=cv2.SOLVEPNP_ITERATIVE)
        if not ok or inliers is None or len(inliers)<35:
            raise ValueError(f'3D camera cannot be verified at frame {n}. No planar fallback was applied.')
        indices=inliers.ravel()
        rv,tv=cv2.solvePnPRefineLM(world[indices],target[indices],K,None,rv,tv)
        projected=cv2.projectPoints(world[indices],rv,tv,K,None)[0].reshape(-1,2)
        error=np.linalg.norm(projected-target[indices],axis=1)
        if np.median(error)>2.2:raise ValueError(f'3D camera reprojection exceeds tolerance at frame {n}.')
        rvec,tvec=rv,tv
        matrix=np.eye(4);matrix[:3,:3]=cv2.Rodrigues(rv)[0];matrix[:3,3]=tv.ravel()
        camera=np.linalg.inv(matrix)@np.diag([1,-1,-1,1])
        samples.append(dict(frame=n,camera_matrix=camera.tolist(),inliers=len(indices),
                            median_match_error_px=round(float(np.median(error)),4),
                            corner_reprojection_rms_px=None,projection_p95_px=float(np.percentile(error,95))))
        if n in {0,len(files)//3,2*len(files)//3,len(files)-1}:
            canvas=cv2.cvtColor(rgb,cv2.COLOR_RGB2BGR)
            for a,b in zip(projected[::8],target[indices][::8]):
                cv2.circle(canvas,tuple(np.rint(a).astype(int)),3,(0,240,90),1)
                cv2.line(canvas,tuple(np.rint(a).astype(int)),tuple(np.rint(b).astype(int)),(0,70,255),1)
            cv2.imencode('.jpg',canvas)[1].tofile(job/f'track-3d-{n:05d}.jpg')
        if n%24==0:print(f'Localized 3D camera {n+1}/{len(files)}, {len(indices)} inliers, {np.median(error):.2f}px',flush=True)
    return samples,dict(minimum_inliers=min(x['inliers'] for x in samples),
        maximum_p95_px=max(x['projection_p95_px'] for x in samples),
        median_reprojection_px=float(np.median([x['median_match_error_px'] for x in samples])))
