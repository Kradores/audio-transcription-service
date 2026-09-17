## HOW TO START
```
git clone <repo>
```
```
cd audio-transcription-service
```
```
uv sync
```

## Definition of Done (DoD)
Before we consider a task complete, we should be able to answer "yes" to something like:
- Requirements implemented
- Unit tests added
- Integration tests added (if applicable)
- Logging added
- Configuration added (if needed)
- Documentation updated
- No linting/type-checking issues
- Commit message follows Conventional Commits
It's a simple checklist, but it prevents the "I'll add tests later" or "I'll document it later" trap.

## ADRs
These are project-specific decisions.

Examples:
- Why Faster-Whisper?
- Why SQLite?
- Why queues?
- Why WASAPI?

ADRs explain why a particular decision was made and can evolve if the project changes.

## Engineering Principles
These are timeless.

## Our workflow from now on
We now have a very clear process:

- We discuss a feature.
- We agree on the design.
- Decide whether:
    1. 🟢 No ADR needed — implementation detail.
    2. 📘 ADR recommended — architectural decision.
- If needed, create/update the ADR.
- We implement.
- We test.
- We update the relevant documentation (if needed).
- We commit.

## About the code itself

From this point onward, present code like a senior engineer opening a pull request:

- specify the file being implemented.
- explain why the code is written that way.
- point out any trade-offs.
- suggest improvements if I see them.
- recommend tests before moving on.

## Code Review Checklist

For every implementation we'll review:

- Correctness
- Readability
- Maintainability
- Testability
- Type safety
- Performance (when relevant)
- Future extensibility
- Consistency with our architecture

If something can be improved, we'll improve it immediately instead of accumulating technical debt.

## Before every commit/merge, ask yourself these four questions:

- Does it compile?
- Does it pass tests?
- Would I understand this in six months?
- Would I approve this if it came from someone else?

If the answer to any of them is "no," we improve it before committing.

It's a simple checklist, but it's remarkably effective at maintaining quality.

## Coding Standards
- Import order (standard library → third-party → local)
- One responsibility per class
- Immutable configuration models
- Logical field ordering (not alphabetical)
- Every public class has a concise docstring
- Every feature must include unit tests
- Use Conventional Commits

## Order inside a class
I'd like every class to follow the same order.
```
class AudioSettings(BaseConfigurationModel):
    """Configuration for audio capture."""

    fields

    properties

    validators
```

## Fields order inside class
Logical grouping instead of alphabetical order

## Runtime filesystem paths

Runtime filesystem locations are represented by the strongly typed `RuntimePaths` boundary.

Development execution uses the repository root as the runtime root. Installed Windows execution uses:

```text
%LOCALAPPDATA%\AudioTranscriptionService
```

Configured relative filesystem paths are resolved against the runtime root, not the process current working directory and not the directory containing `config.yaml`.

The configuration loader receives `RuntimePaths` explicitly and does not discover the runtime root itself.

## Implementation-driven development
Instead of asking "How should we design this?", we'll ask:
"Is this implementation the simplest one that satisfies our architecture?"

## Composition Root Rule
- Objects are created only in the composition root.
- Business classes never instantiate other business classes directly.
- Dependencies are passed through constructors.

This is one of the cleanest habits you can develop, and it will pay off enormously once we start wiring in Whisper, VAD, storage, and the API.

## For future subsystems, Definition of Done
- Architecture agreed
- ADR written (if needed)
- Public API designed
- Implementation complete
- Unit tests complete
- Integration tests (if applicable)
- Documentation updated
- Ruff passes
- MyPy passes
- Pytest passes
- Ready to merge

## Notes
`Application` = runtime application object / owner of long-lived services
`composition.py` = composition function/module that constructs the object graph
```
composition.py
    constructs everything
          ↓
Application
    owns everything
```
---
I recommend PyAudioWPatch as the concrete capture backend for Sprint 3.

We should not expose PyAudioWPatch types outside the infrastructure/adapter layer. Our application should depend on our own `AudioCapture` boundary.

## proposed AudioFrame
Conceptually:
```
AudioFrame
├── samples: numpy.ndarray[int16]
├── sample_rate: int
├── channels: int
├── timestamp: float
└── duration: float
```

with these invariants:
```
samples
    owned by AudioFrame
    PCM signed 16-bit
    native capture sample rate
    native channel count

timestamp
    monotonic seconds since capture started

duration
    seconds represented by this frame

frame duration
    normally exactly 20 ms
```

## What device are we actually capturing?
Capture the Windows default render/output device through its WASAPI loopback endpoint.
```
Windows default output
        │
        ▼
WASAPI render endpoint
        │
        ▼
corresponding loopback endpoint
        │
        ▼
AudioCapture
```
This also handles a common use case naturally:
```
Laptop speakers
      ↓
Bluetooth headphones
      ↓
USB headset
```

## What happens when the default device changes?
Windows changes:
```
Default output:
Speakers → Bluetooth Headphones
```
Our desired behavior is:
```
old stream
    │
    ▼
device change detected
    │
    ▼
stop old stream
    │
    ▼
discover new default output
    │
    ▼
open corresponding loopback
    │
    ▼
resume frames
```

## The implementation sequence for audio
```
Contracts
    ↓
Capture adapter
    ↓
Capture queue/lifecycle
    ↓
Normalizer
    ↓
Silero adapter
    ↓
SpeechSegmentAssembler
    ↓
Pipeline composition
    ↓
Hardware-independent tests
    ↓
Real Windows integration
```

## Database

The application uses SQLite for transcript persistence.

The database path is configured through:

```yaml
database:
  path: data/transcripts.db
```

Relative database paths are resolved against the runtime root.

During development this produces:

```text
<repository>\data\transcripts.db
```

The application does not depend on the process current working directory to locate the database.

The application creates the parent directory for the configured database
path when necessary.

Database schema initialization is performed during application composition.

Schema migrations are intentionally not introduced yet.


## AMD GPU transcription development environment

AMD/TheRock development uses a separate isolated runtime from the project's
normal CPU `.venv`.

The normal CPU workflow remains:

```powershell
uv sync
uv run python -m app
```

### AMD setup — start here

Do not manually execute every script under `scripts/amd`.

The normal AMD entry point is:

```powershell
.\scripts\amd\prepare.ps1
```

This performs the required sequence:

```text
prerequisite validation
        ↓
pinned CTranslate2 source preparation
        ↓
HIP + Intel OpenMP native build
        ↓
native dependency validation
        ↓
custom wheel build
        ↓
fresh GPU runtime smoke test
        ↓
application dependencies
        ↓
CPU Silero validation
        ↓
AMD CTranslate2 revalidation
        ↓
application-ready isolated runtime
```

For a clean native rebuild:

```powershell
.\scripts\amd\prepare.ps1 -Clean
```

For the expensive sustained teardown regression as part of preparation:

```powershell
.\scripts\amd\prepare.ps1 `
    -Clean `
    -RunLongValidation
```

See `scripts/amd/README.md` for the responsibility of each individual stage
script.

### AMD application configuration

The validated AMD transcription configuration is:

```yaml
transcription:
  worker_count: 1

whisper:
  runtime: therock
  model: small
  device: cuda
  compute_type: float16
```

`cuda` is the CTranslate2 device identifier used by its HIP backend.

Do not change it to `rocm`.

### Running the AMD application

After preparation succeeds:

```powershell
$amdPython = Join-Path `
    $env:TEMP `
    "audio-transcription-service-amd\runtime-test-venv\Scripts\python.exe"

& $amdPython -m app
```

Run the application directly when validating graceful shutdown.

Do not pipe the process through `Tee-Object` for lifecycle acceptance because
interrupting the PowerShell pipeline can prevent the final application-owned
shutdown logs from being observed reliably.

The application already owns rotating file logging.

### Dependency isolation

Do not run `uv sync` against the generated AMD runtime.

Do not rely on an ambiguous `uv run` invocation when testing that runtime.

The custom CTranslate2 wheel is part of the validated AMD native runtime and
must not be replaced accidentally by dependency resolution.

The CPU `.venv` and isolated AMD runtime intentionally remain independent.


## Build the Windows packaged application

The current Windows distribution is built with PyInstaller in `onedir` mode.

The build configuration is version-controlled at:

```text
packaging/windows/AudioTranscriptionService.spec
```

Build from the repository root with:

```powershell
.\scripts\windows\build.ps1
```

The output is:

```text
dist/
└── AudioTranscriptionService/
    ├── AudioTranscriptionService.exe
    └── _internal/
```

The Windows distribution is built as a windowed application. It does not
open a console window during normal use.

Runtime diagnostics are written to the application log and exposed through
the controller's operational actions and support-bundle feature.

The PyInstaller configuration explicitly includes:

- `faster_whisper`, because the application loads it dynamically;
- Silero VAD package data, because its model resources are loaded through
  `importlib.resources`.

Do not run the generated executable without the complete `onedir` directory.


## Build the Windows installer

The Windows installer is built with Inno Setup.

Install the compiler once on the development machine:

```powershell
winget install `
    --id JRSoftware.InnoSetup `
    --exact `
    --scope user
```

Build the complete Windows distribution from the repository root:

```powershell
.\scripts\windows\build-installer.ps1
```

The script:

1. rebuilds the PyInstaller `onedir` application;
2. reads the application version from `pyproject.toml`;
3. locates `ISCC.exe`;
4. compiles the Inno Setup installer;
5. prints the resulting installer path, size, and SHA-256 hash.

The resulting installer is written to:

```text
dist/
└── installer/
    └── AudioTranscriptionService-Setup-<version>.exe
```

The current installer is deliberately minimal.

It installs the immutable application runtime under:

```text
%LOCALAPPDATA%\Programs\AudioTranscriptionService\
```

and creates a Start Menu shortcut.

Initial configuration seeding and mutable runtime-data lifecycle behavior are
validated in the next installer-development step.

On first installation, the installer seeds:

```text
%LOCALAPPDATA%\AudioTranscriptionService\config\config.yaml
```

from `config/config.example.yaml`.

The installer never overwrites an existing `config.yaml`.

The configuration file is mutable user data and is preserved across
reinstallations, upgrades, and uninstall.

## Building the Windows NVIDIA Distribution

The NVIDIA runtime is prepared from pinned official NVIDIA Python packages.

Runtime contract:

```text
scripts/nvidia/toolchain.json
```

Prepare/build the NVIDIA application with:

```powershell
.\scripts\windows\build-nvidia.ps1
```

This:

```text
prepares the pinned NVIDIA runtime
    ↓
stages the required native DLLs
    ↓
builds the NVIDIA PyInstaller onedir distribution
    ↓
verifies the packaged NVIDIA DLL contract
```

The application output is:

```text
dist\nvidia\AudioTranscriptionService\
```

The private NVIDIA runtime is packaged under:

```text
_internal\nvidia-runtime\
```

It contains the pinned cuBLAS, cuDNN, and NVRTC DLLs plus `manifest.json`.

### Building the NVIDIA installer

Run:

```powershell
.\scripts\windows\build-nvidia-installer.ps1
```

The script first builds the NVIDIA application and then invokes Inno Setup.

The installer output is:

```text
dist\installer\nvidia\
    AudioTranscriptionService-Nvidia-Setup-<version>.exe
```

The NVIDIA installer seeds:

```text
config/config.nvidia.example.yaml
```

only when the installed user's `config.yaml` does not already exist.

An existing config is preserved.

### NVIDIA smoke-test artifact

The standalone NVIDIA runtime smoke-test remains available for isolated CUDA/CTranslate2 diagnosis:

```powershell
.\scripts\nvidia\build-smoke-test.ps1
```

It is diagnostic tooling and is not the production application distribution.
