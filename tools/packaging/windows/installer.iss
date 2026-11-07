; Script Inno Setup dell'installer per utente di Anonymizer.
; Va compilato tramite build_installer.py, che passa BundleFiles, BundleIcon e
; AppVersion e verifica il bundle portable prima della compilazione.
;
; Richiede un compilatore Inno Setup nell'intervallo supportato.
#if Ver < EncodeVer(6, 5, 2) || Ver >= EncodeVer(7, 0, 0)
  #error Inno Setup >=6.5.2,<7 is required
#endif

; Definizioni obbligatorie fornite da build_installer.py.
#ifndef BundleFiles
  #error BundleFiles must be supplied by build_installer.py
#endif
#ifndef BundleIcon
  #error BundleIcon must be supplied by build_installer.py
#endif
#ifndef AppVersion
  #error AppVersion must be supplied by build_installer.py
#endif
#ifndef LicenseFile
  #error LicenseFile must be supplied by build_installer.py
#endif

; Dati identificativi dell'applicazione, installazione per utente senza privilegi di
; amministratore in %LOCALAPPDATA%, Windows 10 o successivo a 64 bit, compressione.
[Setup]
AppId={{93B01F19-9804-48EF-9A75-F46BA85788DA}
AppName=Anonymizer
AppVersion={#AppVersion}
AppPublisher=Gianluca Braccini
VersionInfoVersion={#AppVersion}
VersionInfoCompany=Gianluca Braccini
VersionInfoDescription=Installazione Anonymizer - uso esclusivamente personale
VersionInfoCopyright=Copyright (C) 2026 Gianluca Braccini
LicenseFile={#LicenseFile}
DefaultDirName={localappdata}\Programs\Anonymizer
DefaultGroupName=Anonymizer
PrivilegesRequired=lowest
ArchitecturesAllowed=x64os
ArchitecturesInstallIn64BitMode=x64os
MinVersion=10.0
WizardStyle=modern
DisableProgramGroupPage=yes
SetupIconFile={#BundleIcon}
UninstallDisplayIcon={app}\Anonymizer.exe
OutputBaseFilename=Anonymizer-Setup-{#AppVersion}-x64
Compression=lzma2/normal
SolidCompression=yes
DiskSpanning=no
CloseApplications=no
RestartApplications=no
Uninstallable=yes

; Interfaccia della procedura di installazione in italiano.
[Languages]
Name: "italian"; MessagesFile: "compiler:Languages\Italian.isl"

; Collegamenti facoltativi scelti dall'utente.
[Tasks]
Name: "startmenuicon"; Description: "Crea un collegamento nel menu Start"; GroupDescription: "Collegamenti:"
Name: "desktopicon"; Description: "Crea un collegamento sul desktop"; GroupDescription: "Collegamenti:"

; Elenco dei file generato da build_installer.py dal bundle verificato.
[Files]
#include BundleFiles

; Collegamenti nel menu Start e sul desktop, legati ai task.
[Icons]
Name: "{autoprograms}\Anonymizer"; Filename: "{app}\Anonymizer.exe"; WorkingDir: "{app}"; Tasks: startmenuicon
Name: "{autodesktop}\Anonymizer"; Filename: "{app}\Anonymizer.exe"; WorkingDir: "{app}"; Tasks: desktopicon

; Avvio facoltativo dell'applicazione al termine dell'installazione.
[Run]
Filename: "{app}\Anonymizer.exe"; Description: "Avvia Anonymizer"; Flags: nowait postinstall skipifsilent unchecked
