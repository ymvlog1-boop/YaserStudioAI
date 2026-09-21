"""محرك Yaser Studio AI المحلي وغير المتلف."""
from pathlib import Path
import sys
import cv2
import numpy as np
from PIL import Image, ImageOps

ROOT=Path(getattr(sys,'_MEIPASS',Path(__file__).parent));MODEL_DIR=ROOT/'models';_session=None;_matte_kind=None
cv2.setNumThreads(6)
TONE_DEFAULTS={k:0 for k in ('exposure','contrast','highlights','shadows','whites','blacks','temperature','tint','vibrance','saturation','clarity','dehaze')}
ENHANCE_DEFAULTS={'denoise':0,'sharpen':0,'upscale':1}
PORTRAIT_DEFAULTS={'skin_light':0,'skin_tone':0,'shine':0,'under_eyes':0,'eyes':0,'teeth':0,'face_detail':0}
BACKGROUND_DEFAULTS={'edge':-2,'feather':2,'decontaminate':65,'blur':0}

def read_image(path,limit=None):
    with Image.open(path) as im:
        im=ImageOps.exif_transpose(im);meta={'exif':im.getexif().tobytes(),'icc_profile':im.info.get('icc_profile')};im=im.convert('RGB')
        if limit:im.thumbnail((limit,limit),Image.Resampling.LANCZOS)
        return np.asarray(im).copy(),meta

def detect_faces(rgb):
    h,w=rgb.shape[:2];scale=min(1,1600/max(w,h));bgr=cv2.cvtColor(cv2.resize(rgb,(round(w*scale),round(h*scale))),cv2.COLOR_RGB2BGR);hh,ww=bgr.shape[:2]
    detector=cv2.FaceDetectorYN.create(str(MODEL_DIR/'face_detection_yunet_2023mar.onnx'),'',(ww,hh),.65,.3,5000);_,rows=detector.detect(bgr);result=[]
    if rows is not None:
        for row in rows:result.append({'box':[float(row[0]/ww),float(row[1]/hh),float(row[2]/ww),float(row[3]/hh)],'points':[[float(row[i]/ww),float(row[i+1]/hh)] for i in range(4,14,2)],'enabled':True})
    return result

def fresh_state():
    return {'faces':None,'strokes':[],'removals':[],'settings':[0,0,0,0],'enhance':dict(ENHANCE_DEFAULTS),'quality_preset':'يدوي','tone':dict(TONE_DEFAULTS),'portrait':dict(PORTRAIT_DEFAULTS),'local_strokes':[],'background':None,'background_options':dict(BACKGROUND_DEFAULTS),'background_strokes':[],'portrait_blur':0,'clothes_iron':0,'clothes_strokes':[],'preset':'يدوي','style_preset':'بدون قالب شامل','ai_result':None}

def normalize_state(state):
    base=fresh_state()
    for key,value in (state or {}).items():
        if key in ('enhance','tone','portrait','background_options') and isinstance(value,dict):base[key].update(value)
        else:base[key]=value
    return base

def stroke_mask(shape,strokes):
    h,w=shape[:2];mask=np.zeros((h,w),np.uint8)
    for s in strokes:
        color=0 if s.get('erase') else 255;diameter=max(1,round(s.get('size',.02)*min(h,w)));pts=[(round(p[0]*w),round(p[1]*h)) for p in s.get('points',[])]
        for a,b in zip(pts,pts[1:]):cv2.line(mask,a,b,color,diameter,cv2.LINE_AA)
        for p in pts:cv2.circle(mask,p,max(1,diameter//2),color,-1,cv2.LINE_AA)
    return mask

def skin_mask(rgb,state):
    h,w=rgb.shape[:2];mask=np.zeros((h,w),np.uint8);excluded=np.zeros_like(mask)
    for f in state.get('faces') or []:
        x,y,fw,fh=f['box'];x*=w;y*=h;fw*=w;fh*=h;target=excluded if not f.get('enabled',True) else mask
        cv2.ellipse(target,(round(x+fw*.5),round(y+fh*.51)),(max(1,round(fw*.45)),max(1,round(fh*.49))),0,0,360,255,-1)
        neck=np.array([[
          [round(x+fw*.31),round(y+fh*.84)],[round(x+fw*.69),round(y+fh*.84)],
          [round(x+fw*.77),round(y+fh*1.52)],[round(x+fw*.23),round(y+fh*1.52)]
        ]],np.int32);cv2.fillPoly(target,neck,255)
        if not f.get('enabled',True):continue
        pts=f.get('points',[])
        if len(pts)>=5:
            for px,py in pts[:2]:cv2.ellipse(mask,(round(px*w),round(py*h)),(max(1,round(fw*.16)),max(1,round(fh*.085))),0,0,360,0,-1)
            mx=(pts[3][0]+pts[4][0])*w/2;my=(pts[3][1]+pts[4][1])*h/2;cv2.ellipse(mask,(round(mx),round(my)),(max(1,round(fw*.25)),max(1,round(fh*.09))),0,0,360,0,-1)
    ycc=cv2.cvtColor(rgb,cv2.COLOR_RGB2YCrCb);mask=cv2.bitwise_and(mask,cv2.inRange(ycc,np.array([12,122,62]),np.array([255,190,150])))
    for s in state.get('strokes',[]):
        sm=stroke_mask(rgb.shape,[dict(s,erase=False)])
        if s.get('erase'):mask[sm>0]=0
        else:mask=np.maximum(mask,sm)
    result=cv2.GaussianBlur(mask,(0,0),max(.7,min(w,h)/700)).astype(np.float32)/255;result[excluded>0]=0
    return result

def face_region_mask(rgb,state):
    h,w=rgb.shape[:2];mask=np.zeros((h,w),np.uint8)
    for f in state.get('faces') or []:
        if not f.get('enabled',True):continue
        x,y,fw,fh=f['box'];cv2.ellipse(mask,(round((x+fw*.5)*w),round((y+fh*.5)*h)),(max(1,round(fw*w*.48)),max(1,round(fh*h*.52))),0,0,360,255,-1)
    return cv2.GaussianBlur(mask,(0,0),max(.8,min(h,w)/900)).astype(np.float32)/255

def _feature_masks(rgb,state):
    h,w=rgb.shape[:2];eyes=np.zeros((h,w),np.uint8);mouth=np.zeros_like(eyes);under=np.zeros_like(eyes)
    for f in state.get('faces') or []:
        if not f.get('enabled',True):continue
        fw=f['box'][2]*w;fh=f['box'][3]*h;pts=f.get('points',[])
        if len(pts)<5:continue
        for px,py in pts[:2]:
            c=(round(px*w),round(py*h));cv2.ellipse(eyes,c,(max(2,round(fw*.13)),max(2,round(fh*.07))),0,0,360,255,-1);cv2.ellipse(under,(c[0],round(c[1]+fh*.08)),(max(2,round(fw*.15)),max(2,round(fh*.07))),0,0,360,255,-1)
        mx=(pts[3][0]+pts[4][0])*w/2;my=(pts[3][1]+pts[4][1])*h/2;cv2.ellipse(mouth,(round(mx),round(my)),(max(2,round(fw*.18)),max(2,round(fh*.065))),0,0,360,255,-1)
    return [cv2.GaussianBlur(m,(0,0),2).astype(np.float32)/255 for m in (eyes,mouth,under)]

def enhance_image(rgb,state):
    cfg=state.get('enhance',ENHANCE_DEFAULTS);denoise=int(cfg.get('denoise',0));sharpen=int(cfg.get('sharpen',0));out=rgb.copy()
    if denoise:
        strength=3+denoise*.09;out=cv2.fastNlMeansDenoisingColored(out,None,strength,strength,7,21)
    if sharpen:
        blur=cv2.GaussianBlur(out,(0,0),.7+sharpen/80);amount=sharpen/100*1.6;out=np.clip(out.astype(np.float32)*(1+amount)-blur.astype(np.float32)*amount,0,255).astype(np.uint8)
    return out

def adjust_tone(rgb,v):
    if not any(v.get(k,0) for k in TONE_DEFAULTS):return rgb.copy()
    a=rgb.astype(np.float32)/255;a*=2**(v.get('exposure',0)/100*2);lum=cv2.cvtColor(np.clip(a*255,0,255).astype(np.uint8),cv2.COLOR_RGB2GRAY).astype(np.float32)/255
    a+=(1-lum)[...,None]**2*(v.get('shadows',0)/100)*.55;a+=lum[...,None]**2*(v.get('highlights',0)/100)*.45
    a+=(v.get('whites',0)/100)*np.clip((lum-.62)/.38,0,1)[...,None]*.3;a+=(v.get('blacks',0)/100)*np.clip((.38-lum)/.38,0,1)[...,None]*.3
    a=(a-.5)*(1+v.get('contrast',0)/100*1.1)+.5;temp=v.get('temperature',0)/100*.16;tint=v.get('tint',0)/100*.12;a[...,0]+=temp-tint*.3;a[...,2]-=temp+tint*.3;a[...,1]+=tint
    hsv=cv2.cvtColor(np.clip(a*255,0,255).astype(np.uint8),cv2.COLOR_RGB2HSV).astype(np.float32);sat=hsv[...,1]/255;hsv[...,1]=np.clip(hsv[...,1]*(1+v.get('saturation',0)/100)+255*(v.get('vibrance',0)/100)*(1-sat)*.65,0,255);a=cv2.cvtColor(hsv.astype(np.uint8),cv2.COLOR_HSV2RGB).astype(np.float32)/255
    gray=cv2.cvtColor(np.clip(a*255,0,255).astype(np.uint8),cv2.COLOR_RGB2GRAY).astype(np.float32)/255
    if v.get('clarity',0):a+=(gray-cv2.GaussianBlur(gray,(0,0),5))[...,None]*v['clarity']/100*1.2
    if v.get('dehaze',0):a+=(gray-cv2.GaussianBlur(gray,(0,0),20))[...,None]*v['dehaze']/100*1.4
    return np.clip(a*255,0,255).astype(np.uint8)

def apply_local_adjustments(rgb,strokes):
    out=rgb.astype(np.float32)
    for s in strokes or []:
        mask=stroke_mask(rgb.shape,[dict(s,erase=False)]).astype(np.float32)/255;mask=cv2.GaussianBlur(mask,(0,0),max(1,s.get('size',.02)*min(rgb.shape[:2])*.18));amount=s.get('amount',35)/100;kind=s.get('kind','brighten')
        if kind=='brighten':target=np.clip(out*(1+amount*.8)+amount*12,0,255)
        elif kind=='darken':target=np.clip(out*(1-amount*.65),0,255)
        elif kind=='highlights':
            lum=cv2.cvtColor(np.clip(out,0,255).astype(np.uint8),cv2.COLOR_RGB2GRAY).astype(np.float32)/255
            weight=np.clip((lum-.48)/.42,0,1)[...,None]
            target=np.clip(out*(1-weight*amount*.72),0,255)
        elif kind=='saturate':
            hsv=cv2.cvtColor(np.clip(out,0,255).astype(np.uint8),cv2.COLOR_RGB2HSV).astype(np.float32);hsv[...,1]=np.clip(hsv[...,1]*(1+amount),0,255);target=cv2.cvtColor(hsv.astype(np.uint8),cv2.COLOR_HSV2RGB).astype(np.float32)
        else:target=cv2.GaussianBlur(out,(0,0),2.5)
        out=out*(1-mask[...,None])+target*mask[...,None]
    return np.clip(out,0,255).astype(np.uint8)

def retouch(rgb,state):
    values=state.get('settings',[0,0,0,0]);portrait=state.get('portrait',PORTRAIT_DEFAULTS)
    if not any(values) and not any(portrait.values()):return rgb.copy()
    mask=skin_mask(rgb,state)
    if not np.any(mask>.001):return rgb.copy()
    src=rgb.astype(np.float32);a=src.copy();med=cv2.medianBlur(rgb,5).astype(np.float32);spot=np.clip((np.max(np.abs(src-med),axis=2)-4)/20,0,1)[...,None];a+=(med-a)*spot*(values[0]/100)
    lum=cv2.cvtColor(rgb,cv2.COLOR_RGB2GRAY);dark=cv2.morphologyEx(lum,cv2.MORPH_BLACKHAT,cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(9,9))).astype(np.float32);soft=cv2.GaussianBlur(a,(0,0),2.2);a+=(soft-a)*np.clip(dark/20,0,.8)[...,None]*(values[1]/100)
    broad=cv2.bilateralFilter(rgb,13,32,8).astype(np.float32);a+=(broad-a)*(values[2]/100)*.7;smooth=cv2.bilateralFilter(np.clip(a,0,255).astype(np.uint8),9,38,6).astype(np.float32);a+=(smooth-a)*(values[3]/100)*.85
    if portrait.get('shine',0):a+=(broad-a)*np.clip((lum.astype(np.float32)-185)/55,0,1)[...,None]*portrait['shine']/100*.7
    a+=portrait.get('skin_light',0)/100*24;tone=portrait.get('skin_tone',0)/100;a[...,0]+=tone*10;a[...,1]+=tone*3;a[...,2]-=tone*7
    out=np.clip(src+(a-src)*mask[...,None],0,255).astype(np.uint8);eyes,mouth,under=_feature_masks(rgb,state)
    if portrait.get('under_eyes',0):
        blurred=cv2.GaussianBlur(out,(0,0),5).astype(np.float32);m=under[...,None]*portrait['under_eyes']/100*.55;out=np.clip(out*(1-m)+(blurred+8)*m,0,255).astype(np.uint8)
    if portrait.get('eyes',0):
        m=eyes[...,None]*portrait['eyes']/100;target=np.clip(out.astype(np.float32)*1.12+8,0,255);out=np.clip(out*(1-m)+target*m,0,255).astype(np.uint8)
    if portrait.get('teeth',0):
        m=mouth[...,None]*portrait['teeth']/100;target=out.astype(np.float32);target[...,2]*=.82;target=target*.82+255*.18;out=np.clip(out*(1-m)+target*m,0,255).astype(np.uint8)
    if portrait.get('face_detail',0):
        strength=portrait['face_detail']/100;soft=cv2.GaussianBlur(out,(0,0),.75+strength*.55).astype(np.float32)
        target=np.clip(out.astype(np.float32)*(1+strength*.9)-soft*(strength*.9),0,255);m=face_region_mask(rgb,state)[...,None]*strength
        out=np.clip(out*(1-m)+target*m,0,255).astype(np.uint8)
    return out

def remove_objects(rgb,removals):
    result=rgb.copy()
    for strokes in removals:
        mask=stroke_mask(result.shape,strokes)
        if np.any(mask):result=cv2.inpaint(result,mask,max(3,round(min(result.shape[:2])*.006)),cv2.INPAINT_TELEA)
    return result

def person_alpha(rgb,options=None,strokes=None):
    global _session,_matte_kind
    import onnxruntime as ort
    if _session is None:
        opts=ort.SessionOptions();opts.intra_op_num_threads=8;opts.inter_op_num_threads=1
        modnet=MODEL_DIR/'modnet_photographic.onnx';_matte_kind='modnet' if modnet.exists() else 'u2net';_session=ort.InferenceSession(str(modnet if modnet.exists() else MODEL_DIR/'u2net_human_seg.onnx'),sess_options=opts,providers=['CPUExecutionProvider'])
    if _matte_kind=='modnet':
        h0,w0=rgb.shape[:2]
        if w0>=h0:new_h=512;new_w=int(w0/h0*512)
        else:new_w=512;new_h=int(h0/w0*512)
        new_h=max(32,new_h-new_h%32);new_w=max(32,new_w-new_w%32);a=cv2.resize(rgb,(new_w,new_h),interpolation=cv2.INTER_AREA).astype(np.float32)/255;a=(a-.5)/.5;pred=_session.run(None,{_session.get_inputs()[0].name:a.transpose(2,0,1)[None]})[0][0,0]
    else:
        a=cv2.resize(rgb,(320,320),interpolation=cv2.INTER_AREA).astype(np.float32);a/=max(float(a.max()),1);a=(a-np.array([.485,.456,.406],np.float32))/np.array([.229,.224,.225],np.float32);pred=_session.run(None,{_session.get_inputs()[0].name:a.transpose(2,0,1)[None]})[0][0,0];pred=(pred-pred.min())/max(float(pred.max()-pred.min()),1e-6)
    h,w=rgb.shape[:2];scale=min(1,2000/max(h,w));size=(max(1,round(w*scale)),max(1,round(h*scale)));guide=cv2.cvtColor(cv2.resize(rgb,size),cv2.COLOR_RGB2GRAY).astype(np.float32)/255;p=cv2.resize(pred,size,interpolation=cv2.INTER_CUBIC);mean=lambda v:cv2.boxFilter(v,-1,(9,9));mi=mean(guide);mp=mean(p);aa=(mean(guide*p)-mi*mp)/(mean(guide*guide)-mi*mi+.0008);alpha=np.clip(mean(aa)*guide+mean(mp-aa*mi),0,1);alpha=cv2.resize(alpha,(w,h),interpolation=cv2.INTER_CUBIC)
    cfg=dict(BACKGROUND_DEFAULTS);cfg.update(options or {});edge=int(cfg.get('edge',-2))
    if edge:
        k=cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(abs(edge)*2+1,)*2);alpha=cv2.erode(alpha,k) if edge<0 else cv2.dilate(alpha,k)
    if cfg.get('feather',0):alpha=cv2.GaussianBlur(alpha,(0,0),float(cfg['feather']))
    for s in strokes or []:
        sm=stroke_mask(rgb.shape,[dict(s,erase=False)]).astype(np.float32)/255;sm=cv2.GaussianBlur(sm,(0,0),max(1,s.get('size',.02)*min(h,w)*.08));alpha=alpha*(1-sm) if s.get('erase') else np.maximum(alpha,sm)
    return np.clip(alpha,0,1)

def replace_background(rgb,path,options=None,strokes=None):
    alpha=person_alpha(rgb,options,strokes)
    with Image.open(path) as bg:back=np.asarray(ImageOps.fit(ImageOps.exif_transpose(bg).convert('RGB'),(rgb.shape[1],rgb.shape[0]),method=Image.Resampling.LANCZOS)).copy()
    cfg=dict(BACKGROUND_DEFAULTS);cfg.update(options or {})
    if cfg.get('blur',0):back=cv2.GaussianBlur(back,(0,0),.2+cfg['blur']/8)
    foreground=rgb.astype(np.float32);decon=cfg.get('decontaminate',0)/100
    if decon:
        edge=((alpha>.02)&(alpha<.98)).astype(np.float32);inner=cv2.erode((alpha>.8).astype(np.uint8),np.ones((3,3),np.uint8),iterations=2);clean=cv2.inpaint(rgb,(1-inner)*(alpha>.02).astype(np.uint8)*255,3,cv2.INPAINT_TELEA).astype(np.float32);m=edge[...,None]*decon*.55;foreground=foreground*(1-m)+clean*m
    return np.clip(foreground*alpha[...,None]+back.astype(np.float32)*(1-alpha[...,None]),0,255).astype(np.uint8)

def blur_original_background(rgb,amount,options=None,strokes=None):
    amount=int(amount or 0)
    if amount<=0:return rgb.copy()
    alpha=person_alpha(rgb,options,strokes);h,w=rgb.shape[:2];scale=min(1,1500/max(h,w));small=cv2.resize(rgb,(max(1,round(w*scale)),max(1,round(h*scale))),interpolation=cv2.INTER_AREA)
    sigma=.8+amount*.18;blur=cv2.GaussianBlur(small,(0,0),sigma*scale if scale<1 else sigma)
    if scale<1:blur=cv2.resize(blur,(w,h),interpolation=cv2.INTER_LINEAR)
    return np.clip(rgb.astype(np.float32)*alpha[...,None]+blur.astype(np.float32)*(1-alpha[...,None]),0,255).astype(np.uint8)

def iron_clothes(rgb,state):
    amount=int(state.get('clothes_iron',0) or 0);strokes=state.get('clothes_strokes') or []
    if amount<=0 and not strokes:return rgb.copy()
    h,w=rgb.shape[:2];manual=stroke_mask(rgb.shape,strokes).astype(np.float32)/255 if strokes else np.zeros((h,w),np.float32)
    if amount>0:
        person=person_alpha(rgb)>0.58;ycc=cv2.cvtColor(rgb,cv2.COLOR_RGB2YCrCb);skin=cv2.inRange(ycc,np.array([12,122,62]),np.array([255,190,150]))>0
        auto=(person&~skin).astype(np.float32);auto[face_region_mask(rgb,state)>.05]=0;mask=np.maximum(auto,manual)
    else:mask=manual;amount=65
    mask=cv2.GaussianBlur(mask,(0,0),max(1,min(h,w)/700));lab=cv2.cvtColor(rgb,cv2.COLOR_RGB2LAB);light=lab[...,0].astype(np.float32)
    sigma_color=14+amount*.16;sigma_space=8+amount*.13;smooth=cv2.bilateralFilter(light,-1,sigma_color,sigma_space);broad=cv2.GaussianBlur(light,(0,0),2.2+amount*.035);target=smooth*.72+broad*.28
    gx=cv2.Sobel(light,cv2.CV_32F,1,0,ksize=3);gy=cv2.Sobel(light,cv2.CV_32F,0,1,ksize=3);edge=np.clip((cv2.magnitude(gx,gy)-10)/42,0,1)
    mix=np.clip(mask*(amount/100)*.88*(1-edge),0,.9);lab[...,0]=np.clip(light*(1-mix)+target*mix,0,255).astype(np.uint8)
    return cv2.cvtColor(lab,cv2.COLOR_LAB2RGB)

def process(rgb,state,final=False):
    state=normalize_state(state);base=rgb
    ai_path=state.get('ai_result')
    if ai_path and Path(ai_path).is_file():
        try:
            ai,_=read_image(ai_path);ai=cv2.resize(ai,(rgb.shape[1],rgb.shape[0]),interpolation=cv2.INTER_LANCZOS4) if ai.shape[:2]!=rgb.shape[:2] else ai
            mask=face_region_mask(rgb,state)[...,None]*.68;base=np.clip(rgb.astype(np.float32)*(1-mask)+ai.astype(np.float32)*mask,0,255).astype(np.uint8) if np.any(mask) else rgb
        except Exception:base=rgb
    out=remove_objects(base,state['removals']);out=enhance_image(out,state);out=adjust_tone(out,state['tone']);out=apply_local_adjustments(out,state['local_strokes']);out=iron_clothes(out,state);out=retouch(out,state)
    if state.get('background'):out=replace_background(out,state['background'],state['background_options'],state['background_strokes'])
    elif state.get('portrait_blur',0):out=blur_original_background(out,state['portrait_blur'],state['background_options'],state['background_strokes'])
    scale=int(state['enhance'].get('upscale',1)) if final else 1
    if scale in (2,4):out=cv2.resize(out,None,fx=scale,fy=scale,interpolation=cv2.INTER_LANCZOS4)
    return out

def save_new(rgb,source,folder,meta,fmt='JPG'):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True);suffix='.png' if fmt=='PNG' else '.jpg';base=Path(source).stem+'_Yaser';i=0;kwargs={k:v for k,v in meta.items() if v}
    if fmt!='PNG':kwargs.update(quality=98,subsampling=0)
    while True:
        dest=folder/(base+('' if i==0 else '_'+str(i))+suffix)
        try:handle=open(dest,'xb');break
        except FileExistsError:i+=1
    try:
        with handle:Image.fromarray(rgb).save(handle,format='PNG' if fmt=='PNG' else 'JPEG',**kwargs)
    except BaseException:dest.unlink(missing_ok=True);raise
    try:
        with Image.open(dest) as check:
            if check.size!=(rgb.shape[1],rgb.shape[0]):raise OSError('أبعاد الملف المحفوظ لا تطابق نتيجة المعالجة')
            check.verify()
    except BaseException:dest.unlink(missing_ok=True);raise
    return str(dest)
