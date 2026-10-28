; Inno Setup script for HabitFlow.
;
; Produces HabitFlow-Setup-<version>.exe: a normal Windows installer that any
; non-technical person can double-click. It installs per-user under
; %LOCALAPPDATA%\Programs\HabitFlow so it never triggers a UAC prompt, adds
; Start Menu and (optional) Desktop shortcuts, and registers a proper
; uninstaller in Apps & features.
;
; Build (after `pyinstaller packaging/habitflow.spec`):
;   iscc /DAppVersion=1.1.1 packaging\habitflow.iss
;
; Your habit data lives in %APPDATA%\HabitFlow and is deliberately NOT removed
; on uninstall; the uninstaller asks first.

#ifndef AppVersion
  #define AppVersion "1.1.1"
#endif

#define AppName        "HabitFlow"
#define AppPublisher   "HabitFlow (open source)"
#define AppURL         "https://github.com/inboxpraveen/Daily-Tracker"
#define AppExeName     "HabitFlow.exe"
#define SourceDir      "..\dist\HabitFlow"

[Setup]
AppId={{7C2E4B18-6E3D-4B4E-9A2C-3F1D8B5A0C41}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}/issues
AppUpdatesURL={#AppURL}/releases
VersionInfoVersion={#AppVersion}
VersionInfoProductName={#AppName}
VersionInfoCompany={#AppPublisher}
VersionInfoDescription={#AppName} Setup

; Per-user install: no admin rights, no UAC prompt, works on locked-down PCs.
PrivilegesRequired=lowest
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
DisableDirPage=auto
AllowNoIcons=yes

LicenseFile=..\LICENSE
OutputDir=..\dist
OutputBaseFilename={#AppName}-Setup-{#AppVersion}
SetupIconFile=..\assets\habitflow.ico
UninstallDisplayIcon={app}\{#AppExeName}
UninstallDisplayName={#AppName} {#AppVersion}
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"

[Files]
Source: "{#SourceDir}\{#AppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#SourceDir}\*";             DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}";                 Filename: "{app}\{#AppExeName}"
Name: "{group}\{#AppName} data folder";     Filename: "{userappdata}\HabitFlow"
Name: "{group}\Uninstall {#AppName}";       Filename: "{uninstallexe}"
Name: "{userdesktop}\{#AppName}";           Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Open {#AppName} now"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}\_internal"

[Code]
{ Offer to remove the habit database, but never do it silently. }
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DataDir: String;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    DataDir := ExpandConstant('{userappdata}\HabitFlow');
    if DirExists(DataDir) then
    begin
      if MsgBox('Also delete your habit history?' + #13#10#13#10 +
                DataDir + #13#10#13#10 +
                'Choose No to keep it. Reinstalling HabitFlow will pick it up again.',
                mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
        DelTree(DataDir, True, True, True);
    end;
  end;
end;
