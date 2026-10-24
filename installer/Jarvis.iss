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
AppName=Mark KH Edition
AppVersion={#AppVersion}
AppPublisher=KyZer_HADOC
AppPublisherURL=https://github.com/KyZer-HADOC/Jarvis
AppSupportURL=https://github.com/KyZer-HADOC/Jarvis/issues
UninstallDisplayName=Mark KH Edition
Uninstallable=yes
DefaultDirName={localappdata}\Programs\Jarvis
DefaultGroupName=Mark KH Edition
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
Source: "..\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion; Excludes: ".git,.github,__pycache__,*.pyc,*.log,*.tmp,venv,python,plugins\*,installer\Output,publish_to_github.bat,ReadMe.txt,plugins.txt,.env,.env.*,token*.json,client_secret*.json,*credentials*.json,config\api_keys.json,config\certs,config\certs\*,config\whatsapp_web,config\whatsapp_web\*,memory\*.json,memory\*.db"
Source: "..\plugins\*"; DestDir: "{app}\plugins"; Flags: recursesubdirs createallsubdirs ignoreversion uninsneveruninstall; Excludes: "__pycache__,*.pyc,*.log,*.tmp"

[Icons]
Name: "{group}\Mark KH Edition"; Filename: "{app}\venv\Scripts\pythonw.exe"; Parameters: """{app}\main.py"""; WorkingDir: "{app}"; IconFilename: "{app}\jarvis.ico"
Name: "{group}\Mark KH Edition (console, for troubleshooting)"; Filename: "{app}\venv\Scripts\python.exe"; Parameters: """{app}\main.py"""; WorkingDir: "{app}"; IconFilename: "{app}\jarvis.ico"
Name: "{group}\Repair Mark KH Edition (reinstall requirements; browser download is optional)"; Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\installer\bootstrap.ps1"" -AppDir ""{app}"""; WorkingDir: "{app}"; IconFilename: "{app}\jarvis.ico"
Name: "{autodesktop}\Mark KH Edition"; Filename: "{app}\venv\Scripts\pythonw.exe"; Parameters: """{app}\main.py"""; WorkingDir: "{app}"; IconFilename: "{app}\jarvis.ico"; Tasks: desktopicon

[Run]
Filename: "{app}\venv\Scripts\pythonw.exe"; Parameters: """{app}\main.py"""; WorkingDir: "{app}"; Description: "Launch JARVIS now"; Flags: nowait postinstall skipifsilent; Check: BootstrapSucceeded

[UninstallDelete]
; Created after install, so Inno does not know about them. The user's keys and memory are left alone.
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
  RemoveApiData: Boolean;
  RemoveRuntimeAndModels: Boolean;
  RemoveCommunityPlugins: Boolean;
  RemovePersonalMemory: Boolean;

function BootstrapSucceeded: Boolean;
begin
  Result := BootstrapOK;
end;

function InitializeUninstall(): Boolean;
var
  Form: TSetupForm;
  TitleText: TNewStaticText;
  HelpText: TNewStaticText;
  ApiBox: TNewCheckBox;
  RuntimeBox: TNewCheckBox;
  PluginsBox: TNewCheckBox;
  MemoryBox: TNewCheckBox;
  OKButton: TNewButton;
  CancelButton: TNewButton;
begin
  Result := True;
  RemoveApiData := False;
  RemoveRuntimeAndModels := True;
  RemoveCommunityPlugins := True;
  RemovePersonalMemory := False;

  { Silent uninstalls remove program files/runtime, but preserve personal data. }
  if UninstallSilent then
    Exit;

  Form := CreateCustomForm(ScaleX(465), ScaleY(325), False, False);
  try
    Form.Caption := 'JARVIS - Uninstall options';
    Form.Position := poScreenCenter;

    TitleText := TNewStaticText.Create(Form);
    TitleText.Parent := Form;
    TitleText.Left := ScaleX(16);
    TitleText.Top := ScaleY(12);
    TitleText.Width := ScaleX(430);
    TitleText.Height := ScaleY(24);
    TitleText.Caption := 'Choose which JARVIS data to delete';
    TitleText.Font.Style := [fsBold];

    HelpText := TNewStaticText.Create(Form);
    HelpText.Parent := Form;
    HelpText.Left := ScaleX(16);
    HelpText.Top := ScaleY(40);
    HelpText.Width := ScaleX(430);
    HelpText.Height := ScaleY(34);
    HelpText.Caption := 'Checked items will be deleted. Unchecked personal data is kept for a future reinstall.';

    ApiBox := TNewCheckBox.Create(Form);
    ApiBox.Parent := Form;
    ApiBox.Left := ScaleX(20);
    ApiBox.Top := ScaleY(82);
    ApiBox.Width := ScaleX(425);
    ApiBox.Height := ScaleY(24);
    ApiBox.Caption := 'API keys, plugin settings and connection credentials';
    ApiBox.Checked := False;

    RuntimeBox := TNewCheckBox.Create(Form);
    RuntimeBox.Parent := Form;
    RuntimeBox.Left := ScaleX(20);
    RuntimeBox.Top := ScaleY(120);
    RuntimeBox.Width := ScaleX(425);
    RuntimeBox.Height := ScaleY(24);
    RuntimeBox.Caption := 'Python runtime, installed packages and downloaded models';
    RuntimeBox.Checked := False;

    PluginsBox := TNewCheckBox.Create(Form);
    PluginsBox.Parent := Form;
    PluginsBox.Left := ScaleX(20);
    PluginsBox.Top := ScaleY(158);
    PluginsBox.Width := ScaleX(425);
    PluginsBox.Height := ScaleY(24);
    PluginsBox.Caption := 'Plugins and extra/community plugin files';
    PluginsBox.Checked := False;

    MemoryBox := TNewCheckBox.Create(Form);
    MemoryBox.Parent := Form;
    MemoryBox.Left := ScaleX(20);
    MemoryBox.Top := ScaleY(196);
    MemoryBox.Width := ScaleX(425);
    MemoryBox.Height := ScaleY(24);
    MemoryBox.Caption := 'Personal memory, notes and saved local data';
    MemoryBox.Checked := False;

    OKButton := TNewButton.Create(Form);
    OKButton.Parent := Form;
    OKButton.Width := ScaleX(90);
    OKButton.Height := ScaleY(25);
    OKButton.Left := Form.ClientWidth - ScaleX(90 + 10 + 90 + 16);
    OKButton.Top := Form.ClientHeight - ScaleY(42);
    OKButton.Caption := 'Continue';
    OKButton.ModalResult := mrOk;
    OKButton.Default := True;

    CancelButton := TNewButton.Create(Form);
    CancelButton.Parent := Form;
    CancelButton.Width := ScaleX(90);
    CancelButton.Height := ScaleY(25);
    CancelButton.Left := Form.ClientWidth - ScaleX(90 + 16);
    CancelButton.Top := Form.ClientHeight - ScaleY(42);
    CancelButton.Caption := 'Cancel';
    CancelButton.ModalResult := mrCancel;
    CancelButton.Cancel := True;

    if Form.ShowModal = mrOk then
    begin
      RemoveApiData := ApiBox.Checked;
      RemoveRuntimeAndModels := RuntimeBox.Checked;
      RemoveCommunityPlugins := PluginsBox.Checked;
      RemovePersonalMemory := MemoryBox.Checked;
      Result := True;
    end
    else
      Result := False;
  finally
    Form.Free;
  end;
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
  if CurUninstallStep = usPostUninstall then
  begin
    if RemoveApiData then
    begin
      DeleteFile(ExpandConstant('{app}\config\api_keys.json'));
      DelTree(ExpandConstant('{app}\config\certs'), True, True, True);
      DelTree(ExpandConstant('{app}\config\whatsapp_web'), True, True, True);
    end;

    if RemoveRuntimeAndModels then
    begin
      DelTree(ExpandConstant('{app}\venv'), True, True, True);
      DelTree(ExpandConstant('{app}\python'), True, True, True);
      DelTree(ExpandConstant('{app}\models'), True, True, True);
      DelTree(ExpandConstant('{app}\model_cache'), True, True, True);
      DelTree(ExpandConstant('{app}\model-cache'), True, True, True);
    end;

    if RemoveCommunityPlugins then
      DelTree(ExpandConstant('{app}\plugins'), True, True, True);

    if RemovePersonalMemory then
      DelTree(ExpandConstant('{app}\memory'), True, True, True);
  end;
end;
