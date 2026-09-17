from pathlib import Path
import sys,hashlib,json,zipfile
sys.path.insert(0,str(Path(__file__).resolve().parent))
from updater import VERSION
root=Path(__file__).resolve().parents[1]
binary=Path(sys.argv[1]).resolve() if len(sys.argv)>1 else root/'rebuilt/YaserStudioAI'
destination=Path(sys.argv[2]).resolve() if len(sys.argv)>2 else root/'release'
destination.mkdir(exist_ok=True,parents=True)
manifest={'product':'YaserStudioAI','format':1,'version':VERSION,'files':{p.relative_to(binary).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in binary.rglob('*') if p.is_file()}}
archive=destination/'Yaser-Studio-AI-Windows.zip'
with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=4) as z:
    z.writestr('YaserStudioAI/update-manifest.json',json.dumps(manifest,indent=2))
    for p in binary.rglob('*'):
        if p.is_file():z.write(p,'YaserStudioAI/Windows/YaserStudioAI/'+p.relative_to(binary).as_posix())
    for folder in ['source','licenses']:
        for p in (root/folder).rglob('*'):
            if p.is_file() and not any(x in p.parts for x in ['__pycache__','models','.build','.build-cache','.venv']):z.write(p,'YaserStudioAI/'+p.relative_to(root).as_posix())
    for name in ['README.md','LICENSE.txt']:
        if (root/name).exists():z.write(root/name,'YaserStudioAI/'+name)
with zipfile.ZipFile(archive) as z:assert z.testzip() is None
sha=hashlib.sha256(archive.read_bytes()).hexdigest();(destination/(archive.name+'.sha256')).write_text(sha+'  '+archive.name+'\n')
print(archive)
