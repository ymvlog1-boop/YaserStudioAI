"""User-selected offline updates, installed alongside the running version."""
from pathlib import Path,PurePosixPath
import json,zipfile,hashlib,tempfile,shutil,os
VERSION='0.5.1'
DEFAULT_REPO='ymvlog1-boop/YaserStudioAI'
PREFIX='YaserStudioAI/Windows/YaserStudioAI/'
REQUIRED={'YaserStudioAI.exe','_internal/models/u2net_human_seg.onnx','_internal/models/face_detection_yunet_2023mar.onnx'}

def install(archive,destination,session=None,progress=lambda n,s:None):
    target=None
    try:
        with zipfile.ZipFile(archive) as z:
            infos=z.infolist()
            if len(infos)>12000 or sum(i.file_size for i in infos)>4*1024**3:raise ValueError('حزمة التحديث كبيرة بصورة غير متوقعة')
            manifest=json.loads(z.read('YaserStudioAI/update-manifest.json'))
            if manifest.get('product')!='YaserStudioAI' or manifest.get('format')!=1:raise ValueError('الحزمة ليست تحديثاً متوافقاً لبرنامج ياسر')
            expected=manifest['files'];selected={};seen=set()
            for info in infos:
                if not info.filename.startswith(PREFIX) or info.is_dir():continue
                name=info.filename[len(PREFIX):];path=PurePosixPath(name)
                if '\\' in name or ':' in name or path.is_absolute() or any(x in ('..','.') or x.endswith((' ','.')) for x in path.parts):raise ValueError('مسار غير آمن داخل الحزمة')
                if (info.external_attr>>16)&0o170000==0o120000:raise ValueError('روابط غير مسموحة داخل التحديث')
                if name.casefold() in seen:raise ValueError('ملف مكرر في حزمة التحديث')
                seen.add(name.casefold());selected[name]=info
            if not REQUIRED.issubset(selected) or set(selected)!=set(expected):raise ValueError('الحزمة ناقصة أو قائمة ملفاتها غير مطابقة')
            parent=Path(destination).resolve();parent.mkdir(parents=True,exist_ok=True)
            if shutil.disk_usage(parent).free<sum(i.file_size for i in selected.values())+100*1024**2:raise ValueError('مساحة التخزين غير كافية')
            target=Path(tempfile.mkdtemp(prefix='YaserStudioAI-update-',dir=parent))
            for index,(name,info) in enumerate(selected.items()):
                path=target.joinpath(*PurePosixPath(name).parts)
                if not path.resolve().is_relative_to(target):raise ValueError('مسار غير آمن')
                path.parent.mkdir(parents=True,exist_ok=True);digest=hashlib.sha256()
                with z.open(info) as src,open(path,'xb') as out:
                    while chunk:=src.read(1024*1024):out.write(chunk);digest.update(chunk)
                if digest.hexdigest()!=expected[name]:raise ValueError('ملف تالف أو معدّل داخل الحزمة: '+name)
                progress(round((index+1)/len(selected)*100),'جارٍ تجهيز النسخة الجديدة…')
            if (target/'YaserStudioAI.exe').read_bytes()[:2]!=b'MZ':raise ValueError('ملف التشغيل غير صالح')
            if session is not None:(target/'continued-session.yaser.json').write_text(json.dumps(session,ensure_ascii=False),encoding='utf-8')
            return target
    except BaseException:
        if target is not None and target.parent==Path(destination).resolve() and target.name.startswith('YaserStudioAI-update-'):shutil.rmtree(target)
        raise

# Public GitHub Releases: no token or user photos are sent.
import re,urllib.request,urllib.error

def repository(value):
    value=value.strip().removeprefix('https://github.com/').rstrip('/').removesuffix('.git')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9_.-]+',value):raise ValueError('اكتب رابط المستودع أو اسم الحساب/المستودع')
    return value

def version(value):
    m=re.fullmatch(r'v?(\d+)\.(\d+)\.(\d+)',value)
    if not m:raise ValueError('رقم إصدار غير مدعوم')
    return tuple(map(int,m.groups()))

def latest(repo):
    repo=repository(repo)
    req=urllib.request.Request('https://api.github.com/repos/'+repo+'/releases/latest',headers={'Accept':'application/vnd.github+json','User-Agent':'YaserStudioAI/'+VERSION})
    try:
        with urllib.request.urlopen(req,timeout=20) as response:data=json.loads(response.read(2*1024*1024))
    except urllib.error.HTTPError as e:
        if e.code==404:raise ValueError('لا يوجد إصدار منشور متاح؛ تأكد من أن المستودع عام وفيه Release.') from e
        raise
    if data.get('draft') or data.get('prerelease') or version(data['tag_name'])<=version(VERSION):return None
    asset=next((a for a in data.get('assets',[]) if a['name']=='Yaser-Studio-AI-Setup.exe'),None)
    if asset is None:asset=next((a for a in data.get('assets',[]) if a['name']=='Yaser-Studio-AI-Windows.zip'),None)
    if asset is None:raise ValueError('الإصدار المنشور لا يحتوي حزمة Windows المطلوبة')
    url=asset['browser_download_url'];digest=asset.get('digest','')
    if not url.startswith('https://github.com/'+repo+'/releases/download/') or not re.fullmatch(r'sha256:[a-fA-F0-9]{64}',digest or ''):raise ValueError('رابط التحديث أو بصمة التحقق غير متاح')
    return {'version':data['tag_name'],'url':url,'sha256':digest[7:].lower(),'size':asset['size'],'installer':asset['name'].endswith('.exe')}

def download(release,folder,progress=lambda n,s:None):
    if not 0<release['size']<2*1024**3:raise ValueError('حجم التحديث غير صالح')
    path=Path(folder)/'update.zip';digest=hashlib.sha256();total=0
    request=urllib.request.Request(release['url'],headers={'User-Agent':'YaserStudioAI/'+VERSION})
    with urllib.request.urlopen(request,timeout=30) as response,open(path,'xb') as out:
        if not response.geturl().startswith('https://'):raise ValueError('اتصال تنزيل غير آمن')
        while chunk:=response.read(1024*1024):
            total+=len(chunk)
            if total>release['size']:raise ValueError('حجم التنزيل لا يطابق الإصدار')
            out.write(chunk);digest.update(chunk);progress(round(total/release['size']*100),'جارٍ تنزيل التحديث…')
    if total!=release['size'] or digest.hexdigest()!=release['sha256']:raise ValueError('التحديث لم يجتز فحص سلامة التنزيل')
    return path
import sys,uuid,subprocess,base64

def installed_directory():
    if getattr(sys,'frozen',False) and (Path(sys.executable).parent/'installed.json').is_file():return Path(sys.executable).parent
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,r'Software\YaserStudioAI') as key:
            path=Path(winreg.QueryValueEx(key,'InstallDir')[0])
            if (path/'installed.json').is_file():return path
    except (ImportError,OSError):pass
    return Path(os.environ.get('LOCALAPPDATA',str(Path.home()/'AppData/Local')))/'Programs/YaserStudioAI'

def stage_installer(release,session,progress=lambda n,s:None,local_file=None,cache_root=None):
    root=Path(cache_root) if cache_root else Path(os.environ['LOCALAPPDATA'])/'YaserStudioAI/updates'
    folder=root/str(uuid.uuid4());folder.mkdir(parents=True)
    setup=folder/'Yaser-Studio-AI-Setup.exe'
    try:
        if local_file:shutil.copyfile(local_file,setup)
        else:
            downloaded=download(release,folder,progress);downloaded.replace(setup)
        with setup.open('rb') as stream:
            if stream.read(2)!=b'MZ':raise ValueError('ملف التثبيت غير صالح')
        saved=folder/'continued-session.yaser.json';saved.write_text(json.dumps(session,ensure_ascii=False),encoding='utf-8')
        return {'setup':str(setup),'session':str(saved),'directory':str(installed_directory()),'result':str(folder/'result.json')}
    except BaseException:
        shutil.rmtree(folder);raise

def start_installer(staged,parent_id=None,test_screenshot=None):
    root=Path(getattr(sys,'_MEIPASS',Path(__file__).parent))
    script=(root/'assets/install-update.ps1').read_text(encoding='utf-8-sig')
    env=os.environ.copy()
    env.update({'YASER_UPDATE_SETUP':staged['setup'],'YASER_UPDATE_SESSION':staged['session'],'YASER_UPDATE_DIR':staged['directory'],'YASER_UPDATE_RESULT':staged['result'],'YASER_UPDATE_PARENT':str(parent_id if parent_id is not None else os.getpid())})
    if test_screenshot:env['YASER_UPDATE_TEST_SCREENSHOT']=str(test_screenshot)
    else:env.pop('YASER_UPDATE_TEST_SCREENSHOT',None)
    command=base64.b64encode(script.encode('utf-16le')).decode('ascii')
    return subprocess.Popen(['powershell.exe','-NoProfile','-NonInteractive','-WindowStyle','Hidden','-EncodedCommand',command],env=env,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
