## Windows runtime filesystem layout

Runtime paths are deterministic and independent of the process current working directory.

Development execution uses the repository root as the runtime root.

Installed per-user Windows execution uses:

```text
%LOCALAPPDATA%\AudioTranscriptionService\
    config\
        config.yaml
    data\
        transcripts.db
    logs\
        audio-transcription-service.log
    diagnostics\
    support\
```

Configured relative filesystem paths resolve against this runtime root. Absolute configured paths remain absolute.

The installed application runtime under `%LOCALAPPDATA%\Programs\AudioTranscriptionService` remains separate from mutable user data.

## runtime concerns:
Windows required
WASAPI available
default render device required
device loss is recoverable
device changes are followed automatically
application remains alive during recovery

## SQLite

Transcript persistence uses a local SQLite database.

The database location is configured through `database.path`.

The configured database directory must be writable by the application.
The application creates the configured parent directory when it does not
already exist.

No external database service is required.

## AMD GPU transcription runtime

AMD acceleration is optional and applies specifically to Faster-Whisper
transcription.

Silero VAD remains CPU-backed.

The currently validated AMD deployment target is:

```text
Windows x86_64
Python 3.14.6
AMD Radeon RX 6800M
gfx1031
TheRock 10.1.0a20260829 packages
custom CTranslate2 4.8.1 wheel
Intel oneAPI OpenMP 2026.1 runtime
```

The custom CTranslate2 wheel contains the validated:

```text
ctranslate2.dll
libiomp5md.dll
```

The production runtime must initialize TheRock before importing
CTranslate2/Faster-Whisper.

An explicitly configured:

```yaml
whisper:
  runtime: therock
```

requires the AMD backend.

Missing or broken AMD native dependencies are startup failures.

The application does not silently fall back to CPU.

The validated AMD transcription settings are:

```yaml
transcription:
  worker_count: 1

whisper:
  runtime: therock
  device: cuda
  compute_type: float16
```

The ordinary CPU deployment remains independent and does not require TheRock,
Intel OpenMP, or the custom HIP-enabled CTranslate2 artifact.

Support for GPU architectures other than `gfx1031` requires a separately built
and validated artifact.

Native AMD build preparation is performed ahead of runtime through
`scripts/amd/prepare.ps1`.

The application must not compile CTranslate2 opportunistically during normal
startup.

## Windows Distribution Profiles

The Windows application is built as separate runtime-specific distributions.

### CPU

```yaml
whisper:
  model: small
  runtime: default
  device: cpu
  compute_type: int8
```

The CPU distribution does not package NVIDIA or AMD GPU runtimes.

### NVIDIA

```yaml
whisper:
  model: small
  runtime: nvidia
  device: cuda
  compute_type: float16

transcription:
  worker_count: 1
```

The NVIDIA distribution packages its CUDA runtime privately with the application.

Validated runtime versions:

```text
CTranslate2           4.8.1
Faster-Whisper        1.2.1
nvidia-cublas-cu12    12.4.5.8
nvidia-cudnn-cu12     9.1.0.70
nvidia-cuda-nvrtc-cu12 12.4.127
```

The target machine requires a compatible NVIDIA graphics driver.

A full CUDA Toolkit installation is not required.

The NVIDIA runtime must not modify machine-wide `PATH`, CUDA configuration, or other global system state.

### AMD

The Windows AMD distribution is:

`dist\amd\AudioTranscriptionService\`

The corresponding installer is built from the same shared Windows
installer architecture used by CPU and NVIDIA.

The currently supported AMD artifact targets `gfx1031`.

Local packaged and installed acceptance has been completed on an
AMD Radeon RX 6800M.

Independent clean-machine acceptance on another compatible AMD system
remains deferred.

Uninstall removes application binaries but intentionally preserves the
mutable runtime root under:

`%LOCALAPPDATA%\AudioTranscriptionService\`

## Packaged distribution metadata

Windows packaged distributions contain deterministic metadata at:

```text
_internal\
    distribution-metadata.json
```

The metadata describes the immutable application artifact rather than mutable
user configuration.

Current packaged profiles are:

```text
CPU
  profile: cpu
  runtime.kind: default

NVIDIA
  profile: nvidia
  runtime.kind: nvidia
```

The NVIDIA metadata additionally records the pinned private runtime components:

```text
cuBLAS  12.4.5.8
cuDNN   9.1.0.70
NVRTC   12.4.127
```

The manifest also records the exact packaged application/Python dependency
versions used for remote diagnostics.

The Windows build fails if the generated metadata is missing from the packaged
artifact or if the packaged copy differs from the generated build copy.

The shared mutable:

```text
%LOCALAPPDATA%\AudioTranscriptionService\config\config.yaml
```

does not define distribution identity.

Therefore a valid diagnostic state may contain:

```text
distribution.profile = nvidia
configuration.whisper.runtime = default
```

for example after switching application distributions while retaining an
existing configuration.

This mismatch is intentionally visible rather than normalized or hidden.

AMD packaged distribution metadata has not yet been integrated into the
Windows packaging flow.

## Switching Runtime Variants

CPU, NVIDIA, and AMD builds are mutually exclusive installed variants.

Before switching variants:

```text
stop application
    ↓
uninstall current variant
    ↓
install new variant
```

Mutable application data is preserved:

```text
%LOCALAPPDATA%\AudioTranscriptionService\
    config\
    data\
    logs\
    diagnostics\
    support\
```

There is one shared user configuration:

```text
config\config.yaml
```

Installers seed a build-appropriate configuration only when `config.yaml` does not already exist.

Existing configuration is never automatically overwritten.

When changing runtime variant, the runtime-specific Whisper configuration must be updated manually when necessary.

## NVIDIA External Acceptance

The NVIDIA installer was externally validated on 2026-09-17 using an NVIDIA GeForce RTX 2080.

Validation covered:

```text
installation without development tooling
private NVIDIA runtime initialization
system-audio capture
microphone capture
CUDA Faster-Whisper transcription
SQLite persistence
zero capture-frame drops
zero transcription rejection
zero transcription failures
graceful shutdown
support-bundle generation
```

The accepted NVIDIA installer was approximately 1.08 GB compressed, with the unpacked application approximately 2.8 GB.

Runtime-size optimization is intentionally deferred until after correctness and portability validation.