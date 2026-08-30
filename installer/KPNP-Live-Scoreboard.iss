#define MyAppName "KPNP Live Scoreboard"
#ifndef MyAppVersion
  #define MyAppVersion "3.6.5"
#endif
#define MyAppExeName "KPNP-Live-Scoreboard.exe"

[Setup]
AppId={{8C6D3BD9-6BCE-42A1-941A-182F599BFB64}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
VersionInfoVersion={#MyAppVersion}
DefaultDirName={autopf}\KPNP Live Scoreboard
DefaultGroupName={#MyAppName}
OutputDir=..\installer-output
OutputBaseFilename=KPNP-Live-Scoreboard-v3-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#MyAppExeName}
SetupIconFile=..\assets\app.ico

[InstallDelete]
; Remove generated payloads left by older Nuitka and PyInstaller builds before
; copying the current package. Settings live in AppData and are not touched.
Type: files; Name: "{app}\*.dll"
Type: files; Name: "{app}\*.pyd"
Type: filesandordirs; Name: "{app}\_internal"
Type: filesandordirs; Name: "{app}\assets"
Type: filesandordirs; Name: "{app}\pycountry"
Type: filesandordirs; Name: "{app}\PySide6"
Type: filesandordirs; Name: "{app}\shiboken6"

[Files]
Source: "..\pyinstaller-dist\KPNP-Live-Scoreboard\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; AppUserModelID: "KPNP.LiveScoreboard.v3"; Tasks: startmenuicon
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; AppUserModelID: "KPNP.LiveScoreboard.v3"; Tasks: desktopicon

[Tasks]
Name: "startmenuicon"; Description: "Create a Start Menu shortcut"; GroupDescription: "Additional shortcuts:"; Flags: checkedonce
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"

[Run]
Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall
