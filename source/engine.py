"""Local, non-destructive image processing for Yaser Studio AI."""
from pathlib import Path
import os, sys, copy
import cv2
import numpy as np
from PIL import Image, ImageOps

ROOT = Path(getattr(sys, '_MEIPASS', Path(__file__).parent))
MODEL_DIR = ROOT / 'models'
_session = None
cv2.setNumThreads(4)

def read_image(path, limit=None):
    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im)
        meta = {'exif': im.getexif().tobytes(), 'icc_profile': im.info.get('icc_profile')}
        im = im.convert('RGB')
        if limit: im.thumbnail((limit, limit), Image.Resampling.LANCZOS)
        return np.asarray(im).copy(), meta

def detect_faces(rgb):
    h,w = rgb.shape[:2]
    scale = min(1, 1400/max(w,h))
    bgr = cv2.cvtColor(cv2.resize(rgb, (round(w*scale), round(h*scale))), cv2.COLOR_RGB2BGR)
    hh,ww=bgr.shape[:2]
    detector=cv2.FaceDetectorYN.create(str(MODEL_DIR/'face_detection_yunet_2023mar.onnx'), '', (ww,hh), 0.75, 0.3, 5000)
    _,rows=detector.detect(bgr)
    result=[]
    if rows is not None:
        for row in rows:
            result.append({'box':[float(row[0]/ww),float(row[1]/hh),float(row[2]/ww),float(row[3]/hh)],
              'points':[[float(row[i]/ww),float(row[i+1]/hh)] for i in range(4,14,2)],'enabled':True})
    return result

def fresh_state():
    return {'faces':None,'strokes':[], 'removals':[], 'settings':[0,0,0,0], 'background':None}

def stroke_mask(shape, strokes):
    h,w=shape[:2]; mask=np.zeros((h,w),np.uint8)
    for s in strokes:
        color=0 if s.get('erase') else 255
        diameter=max(1,round(s['size']*min(h,w)))
        pts=[(round(p[0]*w),round(p[1]*h)) for p in s['points']]
        for a,b in zip(pts,pts[1:]): cv2.line(mask,a,b,color,diameter,cv2.LINE_AA)
        for p in pts: cv2.circle(mask,p,max(1,diameter//2),color,-1,cv2.LINE_AA)
    return mask

def skin_mask(rgb,state):
    h,w=rgb.shape[:2]; mask=np.zeros((h,w),np.uint8); excluded=np.zeros_like(mask)
    for f in state.get('faces') or []:
        x,y,fw,fh=f['box']; x*=w;y*=h;fw*=w;fh*=h
        if not f['enabled']:
            cv2.ellipse(excluded,(round(x+fw/2),round(y+fh/2)),(max(1,round(fw*.55)),max(1,round(fh*.6))),0,0,360,255,-1)
            continue
        face=np.zeros_like(mask)
        cv2.ellipse(face,(round(x+fw*.5),round(y+fh*.51)),(max(1,round(fw*.43)),max(1,round(fh*.48))),0,0,360,255,-1)
        pts=f['points']
        for px,py in pts[:2]:
            cv2.ellipse(face,(round(px*w),round(py*h)),(max(1,round(fw*.17)),max(1,round(fh*.09))),0,0,360,0,-1)
        mx=(pts[3][0]+pts[4][0])*w/2; my=(pts[3][1]+pts[4][1])*h/2
        cv2.ellipse(face,(round(mx),round(my)),(max(1,round(fw*.25)),max(1,round(fh*.1))),0,0,360,0,-1)
        mask=np.maximum(mask,face)
    # Conservative chroma gating; explicit brush strokes bypass this estimate.
    ycc=cv2.cvtColor(rgb,cv2.COLOR_RGB2YCrCb)
    chroma=cv2.inRange(ycc,np.array([15,125,65]),np.array([255,185,145]))
    mask=cv2.bitwise_and(mask,chroma)
    for s in state['strokes']:
        sm=stroke_mask(rgb.shape,[dict(s,erase=False)])
        if s.get('erase'): mask[sm>0]=0
        else: mask=np.maximum(mask,sm)
    sigma=max(.7,min(w,h)/650)
    mask=cv2.GaussianBlur(mask,(0,0),sigma).astype(np.float32)/255
    mask[excluded>0]=0
    return mask

def retouch(rgb,state):
    values=state['settings']
    if not any(values): return rgb.copy()
    mask=skin_mask(rgb,state)
    ys,xs=np.where(mask>.001)
    if not len(xs): return rgb.copy()
    result=rgb.copy()
    # Overlapped tiles bound memory even for high-resolution photographs.
    tile=768; pad=48
    for y in range(int(ys.min())//tile*tile,int(ys.max())+1,tile):
      for x in range(int(xs.min())//tile*tile,int(xs.max())+1,tile):
        y1=max(0,y-pad);x1=max(0,x-pad);y2=min(rgb.shape[0],y+tile+pad);x2=min(rgb.shape[1],x+tile+pad)
        m=mask[y1:y2,x1:x2]
        if not np.any(m>.001):continue
        src=rgb[y1:y2,x1:x2]; a=src.astype(np.float32)
        # Four distinct spatial responses, blended continuously at strength 0..100.
        med=cv2.medianBlur(src,5).astype(np.float32)
        residual=np.max(np.abs(a-med),axis=2)
        spot=np.clip((residual-5)/22,0,1)[...,None]
        a += (med-a)*spot*(values[0]/100)
        lum=cv2.cvtColor(src,cv2.COLOR_RGB2GRAY)
        dark=cv2.morphologyEx(lum,cv2.MORPH_BLACKHAT,cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(9,9))).astype(np.float32)
        soft=cv2.GaussianBlur(a,(0,0),2.2)
        a += (soft-a)*np.clip(dark/20,0,.8)[...,None]*(values[1]/100)
        broad=cv2.bilateralFilter(src,13,32,8).astype(np.float32)
        a += (broad-a)*(values[2]/100)*.7
        smooth=cv2.bilateralFilter(np.clip(a,0,255).astype(np.uint8),9,38,6).astype(np.float32)
        a += (smooth-a)*(values[3]/100)*.85
        blended=np.clip(src.astype(np.float32)+(a-src)*m[...,None],0,255).astype(np.uint8)
        yy=y-y1;xx=x-x1;hh=min(tile,rgb.shape[0]-y);ww=min(tile,rgb.shape[1]-x)
        result[y:y+hh,x:x+ww]=blended[yy:yy+hh,xx:xx+ww]
    return result

def remove_objects(rgb,removals):
    result=rgb.copy()
    for strokes in removals:
        mask=stroke_mask(result.shape,strokes)
        if np.any(mask): result=cv2.inpaint(result,mask,3,cv2.INPAINT_TELEA)
    return result

def person_alpha(rgb):
    global _session
    import onnxruntime as ort
    if _session is None:
        opts=ort.SessionOptions();opts.intra_op_num_threads=6;opts.inter_op_num_threads=1
        _session=ort.InferenceSession(str(MODEL_DIR/'u2net_human_seg.onnx'),sess_options=opts,providers=['CPUExecutionProvider'])
    a=cv2.resize(rgb,(320,320),interpolation=cv2.INTER_AREA).astype(np.float32)
    a/=max(float(a.max()),1)
    a=(a-np.array([.485,.456,.406],np.float32))/np.array([.229,.224,.225],np.float32)
    pred=_session.run(None,{_session.get_inputs()[0].name:a.transpose(2,0,1)[None]})[0][0,0]
    pred=(pred-pred.min())/max(float(pred.max()-pred.min()),1e-6)
    h,w=rgb.shape[:2]
    # Guided edge refinement keeps soft transitions rather than cutting a hard silhouette.
    scale=min(1,1800/max(h,w)); size=(max(1,round(w*scale)),max(1,round(h*scale)))
    guide=cv2.cvtColor(cv2.resize(rgb,size),cv2.COLOR_RGB2GRAY).astype(np.float32)/255
    p=cv2.resize(pred,size,interpolation=cv2.INTER_LINEAR)
    mean=lambda v:cv2.boxFilter(v,-1,(13,13))
    mi=mean(guide);mp=mean(p)
    aa=(mean(guide*p)-mi*mp)/(mean(guide*guide)-mi*mi+.001)
    bb=mp-aa*mi
    alpha=np.clip(mean(aa)*guide+mean(bb),0,1)
    return cv2.resize(alpha,(w,h),interpolation=cv2.INTER_LINEAR)

def replace_background(rgb,path):
    alpha=person_alpha(rgb)
    with Image.open(path) as bg:
        bg=ImageOps.fit(ImageOps.exif_transpose(bg).convert('RGB'),(rgb.shape[1],rgb.shape[0]),method=Image.Resampling.LANCZOS)
        back=np.asarray(bg)
        return np.clip(rgb.astype(np.float32)*alpha[...,None]+back.astype(np.float32)*(1-alpha[...,None]),0,255).astype(np.uint8)

def process(rgb,state):
    out=remove_objects(rgb,state['removals'])
    out=retouch(out,state)
    if state.get('background'):out=replace_background(out,state['background'])
    return out

def save_new(rgb,source,folder,meta,fmt='JPG'):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    suffix='.png' if fmt=='PNG' else '.jpg'
    base=Path(source).stem+'_Yaser';i=0
    kwargs={k:v for k,v in meta.items() if v}
    if fmt!='PNG':kwargs.update(quality=98,subsampling=0)
    while True:
        dest=folder/(base+('' if i==0 else '_'+str(i))+suffix)
        try: handle=open(dest,'xb');break
        except FileExistsError:i+=1
    try:
        with handle:Image.fromarray(rgb).save(handle,format='PNG' if fmt=='PNG' else 'JPEG',**kwargs)
    except BaseException:
        dest.unlink(missing_ok=True);raise
    return str(dest)
