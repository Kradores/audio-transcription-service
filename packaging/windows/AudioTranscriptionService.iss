#define AppName "Audio Transcription Service"
#define AppExecutableName "AudioTranscriptionService.exe"
#define DefaultWhisperModelName "small"

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
OutputBaseFilename={#InstallerBaseFilename}

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

Source: "{#DefaultModelSeedSource}\*"; \
    DestDir: "{localappdata}\AudioTranscriptionService\models\{#DefaultWhisperModelName}"; \
    Flags: ignoreversion recursesubdirs createallsubdirs uninsneveruninstall; \
    Check: ShouldSeedDefaultWhisperModel

[Icons]
Name: "{group}\{#AppName}"; \
    Filename: "{app}\{#AppExecutableName}"; \
    WorkingDir: "{app}"

[Code]

var
  SeedDefaultWhisperModel: Boolean;

function GetDefaultWhisperModelDirectory(): String;
begin
  Result :=
    ExpandConstant(
      '{localappdata}\AudioTranscriptionService\models\{#DefaultWhisperModelName}'
    );
end;

procedure InitializeWizard;
var
  ModelDirectory: String;
begin
  ModelDirectory := GetDefaultWhisperModelDirectory();

  SeedDefaultWhisperModel :=
    not DirExists(ModelDirectory);

  if SeedDefaultWhisperModel then
  begin
    Log(
      'Default Whisper model will be seeded: ' +
      ModelDirectory
    );
  end
  else
  begin
    Log(
      'Existing default Whisper model directory will be preserved: ' +
      ModelDirectory
    );
  end;
end;

function ShouldSeedDefaultWhisperModel(): Boolean;
begin
  Result := SeedDefaultWhisperModel;
end;