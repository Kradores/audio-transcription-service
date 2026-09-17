# ADR-051: Windows NVIDIA Faster-Whisper Runtime Distribution

## Status
Accepted

## Context

The Windows CPU package has passed external acceptance on a second machine. The target external machine also contains an NVIDIA RTX 2080.

Faster-Whisper 1.2.1 uses CTranslate2 4.8.1. Investigation established that the normal CTranslate2 Windows wheel is CUDA-capable and that GPU inference requires CUDA 12-era cuBLAS, cuDNN 9, and NVRTC libraries.

A standalone acceptance artifact was built using pinned NVIDIA packages:

```text
nvidia-cublas-cu12       12.4.5.8
nvidia-cudnn-cu12        9.1.0.70
nvidia-cuda-nvrtc-cu12   12.4.127
```

The artifact bundled these libraries privately, preloaded them before importing CTranslate2, detected the RTX 2080, reported CUDA `float16` support, loaded Faster-Whisper `small` with `device=cuda` and `compute_type=float16`, completed a real transcription, and destroyed the model cleanly.

The working CPU installer must remain unaffected.

## Decision

The project will support NVIDIA acceleration using an application-private CUDA runtime rather than requiring users to install the CUDA Toolkit or cuDNN globally.

The existing CPU package remains a supported independent distribution profile.

A dedicated NVIDIA Windows build profile will package the same application plus the pinned NVIDIA runtime libraries that passed acceptance.

The application will introduce an `NvidiaFasterWhisperRuntimeInitializer`. It will initialize the private NVIDIA DLL search environment before Faster-Whisper/CTranslate2 is imported.

The initializer will not modify permanent system environment variables or machine-wide `PATH`.

The NVIDIA profile will initially use:

```text
model: small
runtime: nvidia
device: cuda
compute_type: float16
worker_count: 1
```

The runtime libraries remain pinned and sourced from official NVIDIA packages during the build process. Build tooling stages only the explicitly approved DLL set and records hashes/version information.

The CPU, NVIDIA, and AMD/TheRock runtime implementations remain replaceable behind the existing Faster-Whisper runtime-initializer abstraction.

## Runtime boundary

```text
Application
    ↓
FasterWhisperFactory
    ↓
configured runtime initializer
    ├── default
    ├── nvidia
    └── therock
    ↓
dynamic import of faster_whisper
    ↓
CTranslate2
```

For NVIDIA:

```text
NvidiaFasterWhisperRuntimeInitializer
    ↓
validate private runtime
    ↓
configure DLL search path
    ↓
preload pinned NVIDIA libraries
    ↓
return
    ↓
import faster_whisper / CTranslate2
```

This ordering is mandatory because CTranslate2 dynamically resolves GPU libraries at runtime.

## Packaging

The CPU distribution remains small relative to the NVIDIA distribution and does not carry NVIDIA libraries.

The NVIDIA distribution contains the private NVIDIA runtime as part of the application package. The exact installer shape—separate CPU and NVIDIA installers initially—is preferred over a single universal installer because it avoids forcing a large GPU payload onto CPU-only systems and keeps failure domains separate.

No CUDA Toolkit installation is required by the application installer.

## Observability

On NVIDIA startup, structured logs should include at least the selected runtime, CTranslate2 version, CUDA device count, supported compute types, NVIDIA GPU/driver information when obtainable, and successful NVIDIA runtime initialization.

Support bundles should include GPU/driver/runtime version metadata but not add sensitive transcript content by default.

## Failure behavior

If the NVIDIA runtime cannot initialize, startup should fail explicitly with an actionable error identifying the missing/incompatible runtime component.

The application should not silently fall back from configured `cuda` to CPU. Silent fallback would make performance and deployment problems difficult to diagnose.

Users can instead install/use the CPU build when GPU support is unavailable.

## Consequences

Positive consequences are a self-contained NVIDIA installation, no manual CUDA setup for nontechnical users, reproducible pinned runtime dependencies, isolation from system CUDA installations, retention of the validated CPU fallback, and reuse of the existing runtime abstraction.

The main costs are a substantially larger NVIDIA distribution, an additional build artifact to maintain, and responsibility for testing/pinning NVIDIA runtime versions.

## Alternatives considered

A full CUDA Toolkit prerequisite was rejected because it adds a large manual system dependency and unnecessary developer tooling.

A single universal installer containing the NVIDIA runtime was deferred because all users would pay the large package-size cost.

Downloading CUDA libraries dynamically on first run was deferred because it adds network dependency, more failure modes, and more complexity than a self-contained installer.

System-wide `PATH`/CUDA configuration was rejected because it mutates the user's machine and makes reproducibility worse.

Silent CPU fallback was rejected because it hides NVIDIA deployment failures.

## Validation

ADR-051 is considered implemented only after the real NVIDIA application build, not just the smoke test, passes on the external RTX 2080 machine with both microphone and system audio, real Faster-Whisper transcription, graceful shutdown, no rejected work under a representative run, and a complete support bundle.
