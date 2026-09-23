; Linguaflow for Windows. The payload is dist\Linguaflow, which the
; build script has already filled: the program, its libraries and the models.

#ifndef AppVersion
  #define AppVersion "0.9.0"
#endif

#define DistDir "..\dist\Linguaflow"

[Setup]
AppId={{A7E3C1D4-8B2F-4E6A-9C15-0F4D2B8E6A31}
AppName=Linguaflow
AppVersion={#AppVersion}
AppVerName=Linguaflow {#AppVersion}
AppPublisher=Linguaflow
DefaultDirName={autopf}\Linguaflow
DefaultGroupName=Linguaflow
DisableProgramGroupPage=no
OutputDir=output
OutputBaseFilename=Linguaflow-setup
; Weights are already compressed. Ultra would spend an hour to save little,
; and a solid archive of several gigabytes asks for more memory than it is
; worth.
Compression=lzma2/fast
SolidCompression=no
; A single Setup.exe cannot pass about 4 GB. The slices sit next to it and
; are part of the installer: copying one file without the others will not run.
DiskSpanning=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=admin
WizardStyle=modern
UninstallDisplayName=Linguaflow

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
Source: "{#DistDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Linguaflow"; Filename: "{app}\Linguaflow.exe"
Name: "{autodesktop}\Linguaflow"; Filename: "{app}\Linguaflow.exe"

[Run]
Filename: "{app}\Linguaflow.exe"; Description: "Запустить Linguaflow"; Flags: nowait postinstall skipifsilent
