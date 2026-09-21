#define AppVersion "0.6.0"
[Setup]
AppId={{A7064431-96F7-4DB7-A268-6AD46B58B761}
AppName=Yaser Studio AI
AppVersion={#AppVersion}
AppPublisher=Yaser
DefaultDirName={localappdata}\Programs\YaserStudioAI
DefaultGroupName=Yaser Studio AI
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\..\release
OutputBaseFilename=Yaser-Studio-AI-Setup
SetupIconFile=..\assets\yaser.ico
UninstallDisplayIcon={app}\YaserStudioAI.exe
Compression=lzma2/fast
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
[Files]
Source: "..\..\rebuilt\YaserStudioAI\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "installed.json"; DestDir: "{app}"; Flags: ignoreversion
[Icons]
Name: "{autodesktop}\Yaser Studio AI"; Filename: "{app}\YaserStudioAI.exe"; WorkingDir: "{app}"
Name: "{group}\Yaser Studio AI"; Filename: "{app}\YaserStudioAI.exe"; WorkingDir: "{app}"
[Registry]
Root: HKCU; Subkey: "Software\YaserStudioAI"; ValueType: string; ValueName: "InstallDir"; ValueData: "{app}"; Flags: uninsdeletevalue
[Run]
Filename: "{app}\YaserStudioAI.exe"; Description: "تشغيل Yaser Studio AI"; Flags: nowait postinstall skipifsilent
