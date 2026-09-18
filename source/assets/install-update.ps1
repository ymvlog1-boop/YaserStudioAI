$ErrorActionPreference='Stop'
Wait-Process -Id ([int]$env:YASER_PARENT) -ErrorAction SilentlyContinue
try {
  $p=Start-Process -FilePath $env:YASER_SETUP -ArgumentList @('/SILENT','/SUPPRESSMSGBOXES','/NORESTART','/NOLAUNCH=1',('/DIR="'+$env:LOCALAPPDATA+'\Programs\YaserStudioAI"')) -Wait -PassThru
  if ($p.ExitCode -ne 0) { throw 'Installer failed' }
  Start-Process -FilePath ($env:LOCALAPPDATA+'\Programs\YaserStudioAI\YaserStudioAI.exe') -ArgumentList @('--resume-session',('"'+$env:YASER_SESSION+'"'))
} catch { exit 1 }