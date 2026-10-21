; JARVIS installer - built with Inno Setup 6 (https://jrsoftware.org/isinfo.php)
;
; What the finished Jarvis-Setup.exe does on the user's PC:
;   * copies the app to  %LOCALAPPDATA%\Programs\Jarvis  (no administrator rights needed)
;   * runs installer\bootstrap.ps1: finds Python 3.11+ (or installs a private copy), creates a
;     virtual environment and installs requirements.txt from the internet
;   * adds Start menu / desktop shortcuts and a "Repair" shortcut that re-runs the bootstrap
;
; It never ships or touches API keys: config\api_keys.json and other private files are excluded below,
; and the app asks for the Gemini key on first launch. Re-running the installer over an existing
; install keeps the user's keys and memory.
;
; Build:  ISCC.exe /DAppVersion=1.0.0 installer\Jarvis.iss      (output: installer\Output\Jarvis-Setup.exe)
; (GitHub Actions does this for you: see .github\workflows\build-installer.yml)
;
; Keep this file ASCII only.

#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif

[Setup]
AppId={{B7E4C1A2-5D3F-4E8A-9C61-2F0A7D5E8B14}
AppName=JARVIS
AppVersion={#AppVersion}
AppPublisher=KyZer_HADOC
AppPublisherURL=https://github.com/KyZer-HADOC/Jarvis
AppSupportURL=https://github.com/KyZer-HADOC/Jarvis/issues
UninstallDisplayName=JARVIS
Uninstallable=yes
DefaultDirName={localappdata}\Programs\Jarvis
DefaultGroupName=JARVIS
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=Output
OutputBaseFilename=Jarvis-Setup
SetupIconFile=..\jarvis.ico
UninstallDisplayIcon={app}\jarvis.ico
LicenseFile=..\LICENSE
Compression=lzma2
SolidCompression=yes
WizardStyle=modern

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Shortcuts:"
Name: "browsers"; Description: "Download Chromium for browser automation (extra ~200 MB)"; GroupDescription: "Optional downloads:"; Flags: unchecked
Name: "firefox"; Description: "Also download Firefox for browser automation (extra ~80 MB)"; GroupDescription: "Optional downloads:"; Flags: unchecked

[Files]
; Private data and build leftovers are excluded so that building on a developer PC can never leak keys.
Source: "..\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion; Excludes: ".git,.github,__pycache__,*.pyc,*.log,*.tmp,venv,python,installer\Output,publish_to_github.bat,.env,.env.*,token*.json,client_secret*.json,*credentials*.json,config\api_keys.json,config\certs,config\certs\*,config\whatsapp_web,config\whatsapp_web\*,memory\*.json,memory\*.db"

[Icons]
Name: "{group}\JARVIS"; Filename: "{app}\venv\Scripts\pythonw.exe"; Parameters: """{app}\main.py"""; WorkingDir: "{app}"; IconFilename: "{app}\jarvis.ico"
Name: "{group}\JARVIS (console, for troubleshooting)"; Filename: "{app}\venv\Scripts\python.exe"; Parameters: """{app}\main.py"""; WorkingDir: "{app}"; IconFilename: "{app}\jarvis.ico"
Name: "{group}\Repair JARVIS (reinstall requirements; browser download is optional)"; Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\installer\bootstrap.ps1"" -AppDir ""{app}"""; WorkingDir: "{app}"; IconFilename: "{app}\jarvis.ico"
Name: "{autodesktop}\JARVIS"; Filename: "{app}\venv\Scripts\pythonw.exe"; Parameters: """{app}\main.py"""; WorkingDir: "{app}"; IconFilename: "{app}\jarvis.ico"; Tasks: desktopicon

[Run]
Filename: "{app}\venv\Scripts\pythonw.exe"; Parameters: """{app}\main.py"""; WorkingDir: "{app}"; Description: "Launch JARVIS now"; Flags: nowait postinstall skipifsilent; Check: BootstrapSucceeded

[UninstallDelete]
; Created after install, so Inno does not know about them. The user's keys and memory are left alone.
Type: filesandordirs; Name: "{app}\venv"
Type: filesandordirs; Name: "{app}\python"
Type: filesandordirs; Name: "{app}\install.log"
Type: filesandordirs; Name: "{app}\__pycache__"
Type: filesandordirs; Name: "{app}\core\__pycache__"
Type: filesandordirs; Name: "{app}\actions\__pycache__"
Type: filesandordirs; Name: "{app}\plugins\__pycache__"
Type: filesandordirs; Name: "{app}\memory\__pycache__"
Type: filesandordirs; Name: "{app}\config\__pycache__"
Type: filesandordirs; Name: "{app}\dashboard\__pycache__"

[Code]
var
  BootstrapOK: Boolean;
  RemovePrivateData: Boolean;

function BootstrapSucceeded: Boolean;
begin
  Result := BootstrapOK;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
  Params: String;
  ShowMode: Integer;
begin
  if CurStep = ssPostInstall then
  begin
    WizardForm.StatusLabel.Caption :=
      'Installing requirements from the internet. A console window shows the progress; the first time takes a few minutes...';
    Params := '-NoProfile -ExecutionPolicy Bypass -File "' + ExpandConstant('{app}\installer\bootstrap.ps1') +
              '" -AppDir "' + ExpandConstant('{app}') + '"';
    if WizardIsTaskSelected('browsers') then
      Params := Params + ' -Browsers';
    if WizardIsTaskSelected('firefox') then
      Params := Params + ' -Firefox';
    if WizardSilent then
      ShowMode := SW_HIDE
    else
      ShowMode := SW_SHOWNORMAL;

    BootstrapOK :=
      Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'), Params, ExpandConstant('{app}'),
           ShowMode, ewWaitUntilTerminated, ResultCode) and (ResultCode = 0);

    if not BootstrapOK then
      SuppressibleMsgBox(
        'JARVIS was copied, but installing its requirements did not finish.' + #13#10 + #13#10 +
        'Check your internet connection, then open  Start menu > JARVIS > Repair JARVIS  to try again.' + #13#10 +
        'Details are in:' + #13#10 + ExpandConstant('{app}\install.log'),
        mbError, MB_OK, IDOK);
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then
  begin
    RemovePrivateData := False;
    if not UninstallSilent then
      RemovePrivateData :=
        MsgBox(
          'Also delete your saved API keys, plugin settings, and personal memory? Choose No to keep them for a future reinstall.',
          mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES;
  end;

  if (CurUninstallStep = usPostUninstall) and RemovePrivateData then
  begin
    DelTree(ExpandConstant('{app}\config'), True, True, True);
    DelTree(ExpandConstant('{app}\memory'), True, True, True);
  end;
end;
