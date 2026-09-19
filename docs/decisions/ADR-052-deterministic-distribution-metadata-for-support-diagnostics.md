# ADR-052: Deterministic Distribution Metadata for Support Diagnostics

## Status

Accepted

## Date

2026-09-18

## Context

The Windows application is distributed as separate runtime profiles:

```text
CPU
NVIDIA
AMD
```

ADR-049 established the Windows packaging/runtime layout.

ADR-050 established the controller/runtime process boundary.

ADR-051 established the separate NVIDIA Faster-Whisper distribution and preserved CPU and AMD as independent runtime profiles.

The Windows controller can create a support bundle containing:

```text
system-info.json
configuration
logs
diagnostic metadata
optional transcript database
```

`system-info.json` currently attempts to discover installed Python package versions using:

```python
importlib.metadata.version(...)
```

This works reliably in a normal development Python environment because Python distribution metadata is available.

It is not a reliable description of a PyInstaller distribution.

External NVIDIA acceptance demonstrated support bundles where packages that were unquestionably present in the packaged application were reported as:

```text
faster-whisper: null
ctranslate2:    null
torch:          null
silero-vad:     null
```

The problem is not that those components are missing.

The problem is that Python package metadata is not necessarily preserved in a form that `importlib.metadata` can discover inside the packaged application.

The application therefore needs a deterministic way to answer a different question:

```text
What was intentionally built into this distribution?
```

This is distinct from:

```text
What Python distribution metadata can this running process currently discover?
```

The distinction is important for remote support.

The developer may only receive a support bundle from a nontechnical external tester and must be able to determine which artifact was actually installed and which runtime components it was built with.

### Configuration is not authoritative distribution metadata

The installed distributions intentionally share one mutable configuration file:

```text
%LOCALAPPDATA%\AudioTranscriptionService\config\config.yaml
```

Existing configuration is preserved when switching distribution variants.

Therefore configuration such as:

```yaml
whisper:
  runtime: nvidia
```

does not prove that the currently installed application is the NVIDIA distribution.

The inverse is also possible: the NVIDIA distribution may be installed while an older CPU-oriented configuration remains present.

Distribution identity must therefore come from the application artifact rather than mutable user configuration.

### Runtime introspection must remain separate

The controller is intentionally isolated from the transcription runtime process.

Creating a support bundle must not require the controller to import:

```text
faster_whisper
ctranslate2
torch
CUDA libraries
TheRock / ROCm libraries
```

or initialize the transcription runtime merely to determine which libraries were packaged.

Doing so would weaken the controller/runtime failure isolation established by ADR-050.

Actual machine information such as:

```text
GPU name
GPU driver version
detected CUDA/HIP devices
supported compute types
successfully initialized native runtime
```

is runtime-observed metadata and is outside the first implementation slice of this ADR.

## Decision

### 1. Distribution metadata will be an application-owned contract

The project will introduce a small strongly typed distribution-metadata model.

Conceptually it represents:

```text
schema version
distribution profile
application version
packaged dependency versions
distribution-specific runtime component versions
```

The supported distribution profiles are:

```text
development
cpu
nvidia
amd
```

`development` represents execution from a source/development environment and prevents development support bundles from falsely claiming to be one of the packaged Windows distributions.

### 2. Packaged distributions will contain a deterministic metadata manifest

Each packaged Windows artifact will contain an application-owned metadata file generated during the build.

Conceptually:

```text
distribution-metadata.json
```

Example NVIDIA metadata:

```json
{
  "schema_version": 1,
  "profile": "nvidia",
  "application_version": "0.1.0",
  "packages": {
    "faster-whisper": "1.2.1",
    "ctranslate2": "4.8.1",
    "torch": "...",
    "silero-vad": "...",
    "pyaudiowpatch": "...",
    "pycaw": "...",
    "soxr": "..."
  },
  "runtime": {
    "kind": "nvidia",
    "components": {
      "cublas": "12.4.5.8",
      "cudnn": "9.1.0.70",
      "nvrtc": "12.4.127"
    }
  }
}
```

The exact JSON representation is an implementation contract and may evolve through its own schema version.

### 3. Metadata will describe build facts rather than rediscovering them at runtime

The manifest will be generated as part of the build process.

For ordinary Python dependencies, the build environment may use Python package metadata to record the exact versions being packaged.

The resulting values become immutable facts embedded in the produced artifact.

For distribution-specific native runtimes, the build will use the same deterministic sources already responsible for preparing those runtimes.

For NVIDIA, the authoritative source includes the pinned NVIDIA runtime/toolchain metadata already used to prepare and validate:

```text
cuBLAS
cuDNN
NVRTC
```

The support subsystem will not inspect DLL filenames and attempt to infer library versions.

### 4. Build metadata must not duplicate manually maintained version constants

Version information must be generated from existing authoritative build inputs where practical.

Examples include:

```text
pyproject.toml
installed build-environment package metadata
scripts/nvidia/toolchain.json
generated NVIDIA runtime manifest
AMD toolchain/runtime metadata
```

The project must avoid creating another manually maintained Python dictionary containing versions already defined elsewhere.

This prevents distribution metadata from drifting away from the artifact it describes.

### 5. Distribution profile is a build fact

The metadata profile is determined by the build being produced.

Conceptually:

```text
CPU build     → profile=cpu
NVIDIA build  → profile=nvidia
AMD build     → profile=amd
```

It will not be inferred from:

```text
config.yaml
available GPU hardware
presence of CUDA DLLs
PATH
environment variables
Whisper device configuration
```

This allows support diagnostics to expose mismatches such as:

```text
installed distribution: nvidia
configured whisper runtime: default
```

rather than silently treating the configuration as distribution identity.

### 6. Development execution remains explicitly supported

Development execution does not require a generated packaged manifest.

The development composition may construct equivalent metadata using the current development environment and identify the profile as:

```text
development
```

This keeps support-bundle behavior useful during normal source-checkout development while preserving a clear distinction from packaged artifacts.

### 7. Distribution metadata will enter support diagnostics through dependency injection

`DefaultSupportInfoCollector` will not know how PyInstaller stores files and will not inspect `sys._MEIPASS`.

Distribution metadata will be supplied through composition.

Conceptually:

```text
Windows entry point / development entry point
        ↓
distribution metadata source
        ↓
run_controller(...)
        ↓
DefaultSupportInfoCollector
        ↓
system-info.json
```

The support collector remains responsible for assembling diagnostic information, not determining how a particular application distribution was built.

### 8. Packaged-path knowledge remains at the packaging/entry-point boundary

PyInstaller-specific path discovery remains outside the generic support collector.

Packaged Windows entry points may resolve the bundled metadata file and pass it into controller composition.

The support subsystem itself must remain independent of:

```text
sys._MEIPASS
PyInstaller directory conventions
installer locations
current working directory
```

This follows the same boundary already used for the private NVIDIA runtime directory.

### 9. Existing Python package discovery remains useful but becomes explicitly best-effort

The existing `importlib.metadata` package discovery will not initially be removed.

It represents observable Python-environment metadata.

It is useful during development and may still provide useful information in some packaged environments.

However it is not authoritative distribution metadata.

`system-info.json` will clearly separate:

```text
distribution metadata
```

from:

```text
best-effort observed Python package metadata
```

A packaged result such as:

```json
"packages": {
  "ctranslate2": null
}
```

therefore no longer means:

```text
CTranslate2 was not packaged
```

because the authoritative packaged version is available separately under the distribution metadata.

### 10. Support diagnostics will expose both installed artifact and mutable configuration

`system-info.json` will contain both:

```text
distribution.profile
```

and the existing:

```text
configuration.whisper.runtime
configuration.whisper.device
configuration.whisper.compute_type
```

They intentionally represent different facts.

This allows remote diagnosis of incorrect or stale configuration after changing distribution variants.

### 11. Distribution metadata failures must not make support diagnostics unusable

A missing or malformed metadata manifest is itself valuable diagnostic information.

Support-bundle creation should therefore degrade gracefully where practical.

Instead of preventing the entire bundle from being created, diagnostics should report that deterministic distribution metadata was unavailable and include a non-sensitive error description.

Build-time validation must still reject packaged artifacts whose expected metadata is missing or invalid.

The intended behavior is therefore:

```text
build-time metadata problem
    → build fails

unexpected installed/runtime metadata problem
    → support bundle still created
    → metadata availability/error is recorded
```

### 12. No native ML/GPU library imports will be performed solely for support-bundle collection

The controller must not import or initialize:

```text
Faster-Whisper
CTranslate2
CUDA
cuDNN
cuBLAS
NVRTC
ROCm/TheRock
```

only to populate deterministic distribution metadata.

The support bundle must remain creatable even when the transcription runtime cannot start.

### 13. GPU and driver detection are explicitly deferred

This ADR establishes the ownership model required for future runtime diagnostics but does not implement machine GPU discovery.

A later slice may add runtime-observed information such as:

```text
GPU name
GPU driver version
CUDA device count
supported compute types
AMD runtime/device information
```

Such values must remain clearly distinct from build/distribution metadata.

### 14. The transcription pipeline is unchanged

This decision does not modify:

```text
capture
normalization
VAD
segment assembly
aggregation
transcription preprocessing
TranscriptionExecutor
adaptive language processing
Faster-Whisper
SQLite persistence
```

It affects only:

```text
build metadata
controller composition
support diagnostics
```

## Resulting diagnostic model

Conceptually:

```text
system-info.json
│
├── python
├── operating_system
├── runtime
│
├── distribution
│   ├── available
│   ├── profile
│   ├── application_version
│   ├── packages
│   └── runtime
│       ├── kind
│       └── components
│
├── packages
│   └── best-effort current Python metadata
│
└── configuration
    └── effective mutable application configuration
```

For a packaged NVIDIA installation, the important relationship becomes:

```text
distribution.profile = nvidia
        │
        │ immutable build fact
        ▼

configuration.whisper.runtime = nvidia
        │
        │ mutable user configuration
        ▼

later runtime observation
        │
        └── whether NVIDIA actually initialized successfully
```

These are intentionally three separate facts.

## Consequences

### Positive

- Support bundles reliably identify the installed distribution.
- Packaged Faster-Whisper and CTranslate2 versions no longer depend on PyInstaller preserving Python distribution metadata.
- NVIDIA runtime versions can be reported from the same pinned build inputs used to create the artifact.
- Future AMD distribution metadata can follow the same contract.
- Configuration/distribution mismatches become visible.
- The controller remains independent of native transcription-library initialization.
- Support bundles remain useful when the runtime fails to start.
- Build metadata is reproducible and testable.
- No global machine configuration is required.
- Development package discovery remains useful rather than being discarded.

### Negative

- Windows builds gain another generated artifact.
- PyInstaller specifications must bundle the metadata manifest.
- Build tooling must validate the manifest.
- A small typed metadata loading/composition component is required.
- Distribution and observed-package information intentionally overlap because they answer different diagnostic questions.
- AMD metadata will require its own build integration when the AMD packaged distribution is implemented.

## Alternatives Considered

### Rely only on `importlib.metadata`

Rejected.

External packaged acceptance demonstrated that valid bundled dependencies may be reported as unavailable because PyInstaller does not guarantee the required distribution metadata layout.

### Bundle every Python `.dist-info` directory

Rejected as the primary solution.

This would make diagnostics dependent on Python packaging internals and would not describe non-Python runtime components such as the private NVIDIA DLL runtime.

It may also unnecessarily increase packaging complexity.

### Infer distribution from `config.yaml`

Rejected.

Configuration is mutable and deliberately survives distribution changes.

It describes intended runtime configuration, not the installed artifact.

### Infer distribution from GPU hardware

Rejected.

A machine containing an NVIDIA GPU may be running the CPU distribution, and the NVIDIA distribution may be installed on a machine where its GPU/runtime cannot initialize.

Hardware and distribution identity are different facts.

### Infer NVIDIA versions from DLL names

Rejected.

DLL filenames do not provide a sufficiently reliable application-owned version contract.

The build already has authoritative pinned runtime metadata.

### Import CTranslate2/Faster-Whisper in the controller

Rejected.

Support-bundle creation must remain available when the transcription runtime cannot initialize.

Importing native ML dependencies in the controller would weaken the process/failure boundary established by ADR-050.

### Put distribution metadata into `config.yaml`

Rejected.

Distribution metadata is immutable artifact information.

`config.yaml` is mutable user/application configuration and intentionally survives upgrades and variant switches.

### Introduce machine/GPU detection in the same slice

Deferred.

Distribution facts and runtime-observed machine facts have different ownership and failure semantics.

They should be implemented and validated independently.

## Testing Requirements

Unit tests must cover at least:

```text
valid distribution metadata parsing
profile parsing
application version parsing
package version parsing
runtime-component parsing
unsupported schema version
invalid profile
missing required values
malformed metadata document
development metadata creation
support collector includes distribution metadata
support collector preserves best-effort package metadata
support collector preserves configuration metadata
metadata failure does not prevent support-info collection
distribution profile is not inferred from config
```

Controller/composition tests should verify:

```text
CPU entry point provides CPU metadata
NVIDIA entry point provides NVIDIA metadata
development execution identifies development metadata
support collector receives metadata through dependency injection
```

Build validation must verify:

```text
CPU artifact contains distribution-metadata.json
NVIDIA artifact contains distribution-metadata.json
metadata profile matches the build profile
application version matches the built application
required packaged dependency versions are populated
NVIDIA runtime component versions match pinned build inputs
```

A packaged acceptance should create a support bundle and verify that the resulting `system-info.json` reports deterministic values even if:

```text
importlib.metadata.version("faster-whisper")
```

or other packaged Python metadata discovery would otherwise fail.

## Documentation Impact

### `architecture.md`

Document the distinction between:

```text
distribution metadata
runtime-observed metadata
mutable application configuration
```

and show that distribution metadata enters controller/support composition from the packaging boundary.

### `deployment.md`

Document the metadata manifest embedded in CPU/NVIDIA/AMD distributions and its role in remote diagnostics.

### `development.md`

Document generation and validation of distribution metadata during Windows builds.

### `observability.md`

Document the new `system-info.json` distribution section and clarify that the existing package discovery is best-effort runtime observation.

### `testing.md`

Document build validation and packaged support-bundle acceptance for deterministic distribution metadata.

## Implementation and Validation

The first implementation slice is complete for the Windows CPU and NVIDIA
distributions.

The application now has an application-owned typed distribution metadata
contract with explicit profiles:

```text
development
cpu
nvidia
amd
```

Development execution constructs metadata from the current Python environment.

Packaged CPU and NVIDIA distributions instead contain a generated immutable:

```text
distribution-metadata.json
```

The manifest is generated during the Windows build and bundled inside the
PyInstaller application.

Distribution metadata is injected into support diagnostics rather than being
rediscovered from mutable configuration or inferred from installed hardware.

The support bundle now distinguishes three separate facts:

```text
distribution metadata
    → what this artifact was built as

configuration
    → what the user currently configured

observed Python package metadata
    → what importlib.metadata can discover at runtime
```

This distinction was validated in a packaged NVIDIA controller where:

```text
distribution.profile = nvidia

configuration.whisper.runtime = default
configuration.whisper.device = cpu
```

The artifact identity therefore remained correct even when the preserved
mutable configuration requested CPU execution.

### CPU packaged acceptance

The production CPU PyInstaller build generated and bundled:

```text
profile: cpu
application_version: 0.1.0
runtime.kind: default

faster-whisper: 1.2.1
ctranslate2: 4.8.1
torch: 2.13.0
silero-vad: 6.2.1
```

The generated build manifest and packaged manifest were verified to be
identical.

A real support bundle created by the packaged CPU controller reported:

```text
distribution.available = true
distribution.profile = cpu
```

while the existing best-effort Python package discovery returned `null` for
the packaged dependencies.

This confirms that the deterministic manifest solves the original packaged
dependency-identification problem.

### NVIDIA packaged acceptance

The production NVIDIA PyInstaller build generated and bundled:

```text
profile: nvidia
application_version: 0.1.0
runtime.kind: nvidia

faster-whisper: 1.2.1
ctranslate2: 4.8.1

cublas: 12.4.5.8
cudnn: 9.1.0.70
nvrtc: 12.4.127
```

The existing twelve-DLL NVIDIA runtime contract remained unchanged.

A real support bundle created by the packaged NVIDIA controller reported the
same deterministic distribution metadata without starting the transcription
runtime or loading CUDA/Faster-Whisper.

This validates the ADR-050 failure-isolation requirement: support diagnostics
remain usable independently from the native transcription runtime.

### Build validation

CPU and NVIDIA build scripts now fail when:

- deterministic distribution metadata cannot be generated;
- required Python package metadata is unavailable;
- the NVIDIA Python runtime does not match the pinned NVIDIA toolchain;
- prepared NVIDIA native runtime versions do not match the pinned toolchain;
- the generated manifest is not included in the packaged application;
- the packaged manifest differs from the generated build manifest.

### Final quality gate

After CPU and NVIDIA packaged acceptance:

```text
ruff format:
221 files unchanged

ruff check:
all passed

mypy:
Success — 162 source files

pytest:
593 passed
```

The two existing Python 3.14 `torch.jit.load` deprecation warnings remain
known and unrelated.

### Development source-mode metadata hardening

Development distribution metadata must not require the application itself to be installed into the active Python environment as package metadata.

Specialized development environments such as the ADR-044 TheRock environment may execute the repository directly:

```text
python -m app.controller.main
```

without installing:

```text
audio-transcription-service
```

as a Python distribution.

For the `development` profile:

```text
application version
    → [project].version from repository pyproject.toml
```

Other dependency versions remain best-effort environment observations through Python package metadata.

This preserves the distinction:

```text
development distribution identity
    deterministic from project source metadata

environment package discovery
    best effort
```

Packaged CPU/NVIDIA/AMD distributions remain unchanged and continue to use their generated deterministic `distribution-metadata.json`.

Real TheRock development support-bundle acceptance confirmed:

```text
distribution.available = true
distribution.profile = development
distribution.application_version = 0.1.0
```

even though the legacy best-effort package section may still report:

```text
packages.audio-transcription-service = null
```

This is expected and does not affect deterministic distribution identity.

Replace ADR-052's previous runtime-observation `Remaining scope` list with:

### Follow-up scope

Runtime-observed GPU, driver, and initialized CTranslate2 capability diagnostics are defined separately by ADR-053.

AMD packaged distribution metadata remains part of the future AMD Windows distribution milestone and must use the same deterministic manifest contract established here.

### Remaining scope

The following parts of the broader support-diagnostics milestone remain
separate follow-up work:

```text
GPU name
GPU driver version
runtime-observed CUDA/device information
supported compute types
AMD packaged distribution metadata
AMD/TheRock runtime-observed metadata
```

These are intentionally not inferred from deterministic build metadata.

## Related Decisions

- ADR-005 — Architectural Boundaries
- ADR-014 — Package Dependency Direction
- ADR-016 — Application Composition Root
- ADR-017 — Logging Strategy
- ADR-044 — AMD GPU Transcription Runtime and CPU Fallback Strategy
- ADR-049 — Windows End-User Packaging, Runtime Layout and Interactive Control Host
- ADR-050 — Interactive Controller and Transcription Runtime Process Boundary
- ADR-051 — Windows NVIDIA Faster-Whisper Runtime Distribution