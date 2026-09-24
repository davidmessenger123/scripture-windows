; Scripture — Inno Setup installer script.
;
; Compile with (from the repo root, after building dist\Scripture.exe):
;   "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" /DAppVersion=MAJOR.MINOR.PATCH installer\scripture.iss
;
; The installer is per-user (no admin / UAC prompt needed) and produces
; dist\Scripture-Setup-<version>.exe.

#ifndef AppVersion
  #error AppVersion must be supplied by the versioned build script
#endif

[Setup]
AppId={{c0082d92-2faf-4fe3-87db-22388066285e}}
AppName=Scripture
AppVersion={#AppVersion}
AppVerName=Scripture {#AppVersion}
AppPublisher=David Messenger
AppPublisherURL=https://github.com/davidmessenger123/scripture-windows
AppSupportURL=https://github.com/davidmessenger123/scripture-windows
DefaultDirName={localappdata}\Programs\Scripture
DisableProgramGroupPage=yes
DefaultGroupName=Scripture
UninstallDisplayIcon={app}\Scripture.exe
UninstallDisplayName=Scripture
Compression=lzma2
SolidCompression=yes
; Paths below are relative to this script file's directory (installer/), so
; repo-root assets/ and dist/ are reached with a leading ..\.
OutputDir=..\dist
OutputBaseFilename=Scripture-Setup-{#AppVersion}
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
SetupIconFile=..\assets\app.ico
WizardStyle=modern
WizardSizePercent=115

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop icon"; Flags: unchecked
Name: "startup"; Description: "&Start Scripture when I sign in (runs in the tray)"; GroupDescription: "Autostart:"

[Files]
Source: "..\dist\Scripture.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\Scripture"; Filename: "{app}\Scripture.exe"; IconFilename: "{app}\Scripture.exe"
Name: "{userstartup}\Scripture"; Filename: "{app}\Scripture.exe"; Tasks: startup
Name: "{autodesktop}\Scripture"; Filename: "{app}\Scripture.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Scripture.exe"; Description: "Launch Scripture now"; Flags: nowait postinstall skipifsilent