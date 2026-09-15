#define AppName "Audio Transcription Service"
#define AppExecutableName "AudioTranscriptionService.exe"

[Setup]
AppId={{A7CFF1CD-77E2-4F51-B86D-DAB916E534AA}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=Alexandru Noroc

DefaultDirName={localappdata}\Programs\AudioTranscriptionService
DefaultGroupName={#AppName}

PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible

DisableDirPage=yes
DisableProgramGroupPage=yes

OutputDir="{#InstallerOutputDir}"
OutputBaseFilename=AudioTranscriptionService-Setup-{#AppVersion}

Compression=lzma2
SolidCompression=yes
WizardStyle=modern

UninstallDisplayIcon={app}\{#AppExecutableName}

[Files]
Source: "{#AppSourceDir}\*"; \
    DestDir: "{app}"; \
    Flags: ignoreversion recursesubdirs createallsubdirs

Source: "{#DefaultConfigSource}"; \
    DestDir: "{localappdata}\AudioTranscriptionService\config"; \
    DestName: "config.yaml"; \
    Flags: onlyifdoesntexist uninsneveruninstall

[Icons]
Name: "{group}\{#AppName}"; \
    Filename: "{app}\{#AppExecutableName}"; \
    WorkingDir: "{app}"