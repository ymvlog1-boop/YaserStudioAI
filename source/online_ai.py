"""اختياري: تحسين الوجه عبر مساحة GFPGAN العامة على Hugging Face."""
from pathlib import Path
from PIL import Image,ImageOps
import hashlib,os

SPACE='Gemini899/GFPGAN-Fix'

def _paths(value):
    if isinstance(value,(str,Path)):yield Path(value)
    elif isinstance(value,dict):
        for key in ('path','name','url'):
            if key in value:yield from _paths(value[key])
    elif isinstance(value,(list,tuple)):
        for item in value:yield from _paths(item)

def enhance(source,token=None):
    from gradio_client import Client,handle_file
    source=Path(source);client=Client(SPACE,token=token or None,verbose=False)
    try:result=client.predict(handle_file(str(source)),'v1.4',1,api_name='/predict')
    except Exception as exc:
        message=str(exc)
        if 'quota' in message.lower():raise RuntimeError('نفدت حصة Hugging Face المجانية. أدخل مفتاح حساب مجاني من زر إعداد خدمة AI ثم حاول مجدداً.') from exc
        raise RuntimeError('تعذر الوصول إلى خدمة GFPGAN العامة: '+message) from exc
    found=next((p for p in _paths(result) if p.is_file()),None)
    if found is None:raise RuntimeError('لم تُرجع خدمة التحسين صورة صالحة')
    cache=Path(os.environ.get('YASER_AI_CACHE') or (Path(os.environ.get('LOCALAPPDATA',Path.home()))/'YaserStudioAI'/'ai-cache'));cache.mkdir(parents=True,exist_ok=True)
    digest=hashlib.sha256(source.read_bytes()).hexdigest()[:20];dest=cache/(digest+'-gfpgan.png')
    with Image.open(found) as im:ImageOps.exif_transpose(im).convert('RGB').save(dest,'PNG',compress_level=2)
    return str(dest)
