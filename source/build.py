from pathlib import Path
import subprocess,sys,os
root=Path(__file__).resolve().parent
assets=root
if not (root/'models/u2net_human_seg.onnx').exists():
    assets=root.parent/'Windows/YaserStudioAI/_internal'
assert (assets/'models/u2net_human_seg.onnx').exists(), 'Models are missing'
fonts=root/'fonts' if (root/'fonts').exists() else assets/'fonts'
env=os.environ.copy();env['PYINSTALLER_CONFIG_DIR']=str(root/'.build-cache')
subprocess.run([sys.executable,'-m','PyInstaller','--noconfirm','--windowed','--name','YaserStudioAI',
 '--distpath',str(root.parent/'rebuilt'),'--workpath',str(root/'.build'),'--specpath',str(root/'.build'),
 '--add-data',str(assets/'models')+os.pathsep+'models','--add-data',str(fonts)+os.pathsep+'fonts',
 '--icon',str(root/'assets/yaser.ico'),'--add-data',str(root/'assets')+os.pathsep+'assets','--collect-all','onnxruntime',str(root/'main.py')],check=True,env=env)
