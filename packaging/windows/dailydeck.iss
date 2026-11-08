; Inno Setup script for Daily Deck; compiled by scripts/build-windows.ps1:
;   ISCC /DAppVersion=0.3.0 /DSourceDir=dist\Daily Deck /DIconFile=build\windows\DailyDeck.ico
;        /DOutputDir=dist packaging\windows\dailydeck.iss
;
; Installs per user without admin rights by default (the setup offers "for all users" too).
; The configuration in %APPDATA%\dailydeck is never touched.

#ifndef AppVersion
  #error AppVersion must be defined
#endif

#define AppName "Daily Deck"
#define AppExe "Daily Deck.exe"
#define AppUserModelID "io.github.thnow.dailydeck"
; same value name as dailydeck/autostart.py, so the tray menu shows and changes this entry
#define RunValue "dailydeck"

[Setup]
AppId={{214FBB44-7E72-45E2-8B07-A71692DC1E05}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Thomas Wittmann
AppPublisherURL=https://github.com/thnow/dailydeck
AppSupportURL=https://github.com/thnow/dailydeck/issues
AppUpdatesURL=https://github.com/thnow/dailydeck/releases
AppCopyright=© Thomas Wittmann, GPL-3.0-or-later
VersionInfoVersion={#AppVersion}
VersionInfoProductName={#AppName}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; Qt 6 needs Windows 10 1809 or later
MinVersion=10.0.17763
SetupIconFile={#IconFile}
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes
CloseApplications=force
RestartApplications=no
OutputDir={#OutputDir}
OutputBaseFilename=DailyDeck-{#AppVersion}-windows-x64-setup

[Languages]
Name: "en"; MessagesFile: "compiler:Default.isl"
Name: "de"; MessagesFile: "compiler:Languages\German.isl"

[CustomMessages]
en.AutostartTask=Start Daily Deck when I sign in
de.AutostartTask=Daily Deck bei der Anmeldung starten
en.Editor=Daily Deck Profile Editor
de.Editor=Daily Deck Profil-Editor
en.Launch=Start Daily Deck now
de.Launch=Daily Deck jetzt starten
en.ElgatoHint=Quit the Elgato Stream Deck software first – only one program can use the deck at a time.
de.ElgatoHint=Beende vorher die Elgato-Stream-Deck-Software – nur ein Programm kann das Deck gleichzeitig verwenden.

[Messages]
en.FinishedLabel=Setup has finished installing [name] on your computer. Daily Deck runs in the notification area of the taskbar.%n%n{cm:ElgatoHint}
de.FinishedLabel=[name] wurde auf diesem Computer installiert. Daily Deck läuft im Infobereich der Taskleiste.%n%n{cm:ElgatoHint}

[Tasks]
Name: "autostart"; Description: "{cm:AutostartTask}"
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\..\LICENSE"; DestDir: "{app}"; DestName: "LICENSE.txt"; Flags: ignoreversion
Source: "..\..\README.md"; DestDir: "{app}"; Flags: ignoreversion

[InstallDelete]
; files of an older version that a new one no longer has
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"; AppUserModelID: "{#AppUserModelID}"
Name: "{autoprograms}\{cm:Editor}"; Filename: "{app}\{#AppExe}"; Parameters: "--gui"; IconFilename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "{#RunValue}"; ValueData: """{app}\{#AppExe}"" ""--tray"""; Tasks: autostart; Flags: uninsdeletevalue

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:Launch}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{sys}\taskkill.exe"; Parameters: "/F /IM ""{#AppExe}"""; Flags: runhidden; RunOnceId: "StopDailyDeck"

[Code]
// The Run entry may also have been created later from the tray menu. Remove it only if it
// starts this installation – not, say, a Daily Deck run from a source checkout.
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Command: String;
begin
  if (CurUninstallStep = usPostUninstall) and
     RegQueryStringValue(HKEY_CURRENT_USER, 'Software\Microsoft\Windows\CurrentVersion\Run', '{#RunValue}', Command) and
     (Pos(Lowercase(ExpandConstant('{app}\{#AppExe}')), Lowercase(Command)) > 0) then
    RegDeleteValue(HKEY_CURRENT_USER, 'Software\Microsoft\Windows\CurrentVersion\Run', '{#RunValue}');
end;
