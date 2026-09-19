# ADR-053: Runtime-Observed Hardware and Transcription Diagnostics Across the Controller Process Boundary

## Status

Accepted

## Date

2026-09-19

## Context

ADR-052 introduced deterministic distribution metadata for support diagnostics.

That metadata answers questions such as:

```text
which distribution profile was built?
which application version is this?
which Faster-Whisper/CTranslate2 versions were packaged?
which NVIDIA runtime components were bundled?
```

Those are build/distribution facts.

They do not answer separate runtime questions such as:

```text
which graphics adapters does Windows currently see?
which driver versions are installed?
did the configured transcription runtime actually initialize?
how many accelerator devices can CTranslate2 currently see?
which compute types does the initialized CTranslate2 runtime support?
```

These distinctions matter because the following states are not equivalent:

```text
NVIDIA distribution installed
```

```text
NVIDIA GPU visible to Windows
```

```text
CTranslate2 successfully initialized CUDA
```

Likewise, the AMD/TheRock runtime uses CTranslate2's CUDA-facing device APIs even though the physical accelerator is AMD.

Configuration alone is therefore not sufficient to describe runtime capability.

ADR-050 also established an explicit process boundary:

```text
Windows Controller
        ↓
spawned runtime process
        ↓
Application / Faster-Whisper / native runtime
```

The controller must remain isolated from native transcription-runtime initialization.

Importing or initializing CTranslate2, CUDA, TheRock, Faster-Whisper, or similar native runtime state solely to create a support bundle would violate that boundary and could make diagnostics themselves capable of causing startup or native-runtime failures.

We therefore need runtime-observed diagnostics while preserving process isolation.

---

## Decision

### 1. Distribution metadata, machine observation, and transcription-runtime observation are separate concepts

Support diagnostics distinguish three independent sources of truth.

```text
distribution
    immutable build/source identity

hardware
    operating-system-observed machine state

transcription_runtime
    capabilities observed from the initialized transcription runtime
```

Mutable configuration remains separate:

```text
configuration
    what the user requested
```

No one layer is inferred from another.

For example:

```text
distribution.profile = amd
```

does not imply:

```text
hardware contains AMD GPU
```

and:

```text
configuration.whisper.device = cuda
```

does not imply:

```text
CTranslate2 successfully initialized an accelerator
```

---

### 2. Runtime observations are collected inside the spawned runtime process

The controller process must not import or initialize native ML/GPU runtimes solely for diagnostics.

Runtime observation therefore follows the existing ADR-050 process boundary:

```text
runtime child
    ↓
collect observation
    ↓
typed runtime event
    ↓
status queue
    ↓
RuntimeProcessHost
    ↓
diagnostic snapshot
```

The controller receives plain typed diagnostic data only.

---

### 3. Windows graphics inventory uses the operating-system boundary

Graphics adapters are observed through Windows:

```text
Win32_VideoController
```

using PowerShell/CIM.

The initial observation records every returned adapter with:

```text
name
driver_version
pnp_device_id
```

The implementation does not depend on NVIDIA-, AMD-, or Intel-specific tooling.

The result is represented as an application-owned typed observation.

A machine with multiple adapters retains all adapters rather than choosing or inferring a preferred GPU.

---

### 4. Hardware observation occurs before application startup

The spawned runtime process performs the Windows graphics observation before the transcription application starts.

Conceptually:

```text
spawn runtime child
        ↓
observe Windows graphics adapters
        ↓
publish hardware diagnostic event
        ↓
initialize application
```

This allows hardware information to remain available even when later application or transcription-runtime initialization fails.

Hardware-observation failure is diagnostic only and must not prevent normal application startup.

Observation failures are represented explicitly using:

```text
available = false
error_type
error
```

rather than raising through the runtime lifecycle.

---

### 5. Transcription-runtime observation occurs only after successful application startup

CTranslate2 capabilities are observed only after the configured application has successfully initialized.

The exact loaded `Settings` instance from the successfully started application is used.

The diagnostic layer does not reload `config.yaml` independently.

Conceptually:

```text
Application.start()
        ↓
successful runtime initialization
        ↓
RuntimeStartedEvent
        ↓
observe CTranslate2 capabilities
        ↓
RuntimeTranscriptionObservedEvent
```

Diagnostics therefore inspect the runtime that actually initialized rather than creating a second runtime.

---

### 6. Runtime-start notification is not delayed by diagnostics

Once application startup succeeds, the runtime publishes:

```text
RuntimeStartedEvent
```

before querying the optional CTranslate2 diagnostic information.

Therefore:

```text
diagnostic query failure
```

must never become:

```text
application startup failure
```

The lifecycle and diagnostics event streams remain semantically separate.

---

### 7. CTranslate2 observation is vendor-neutral

For explicit CPU configuration:

```text
device = cpu
```

the observer queries CTranslate2-supported CPU compute types.

For accelerator configuration:

```text
device = cuda
```

the observer queries:

```text
get_cuda_device_count()
get_supported_compute_types("cuda", ...)
```

The term `cuda` in this diagnostic contract refers to the CTranslate2 device API.

It must not be interpreted as proof that the physical GPU vendor is NVIDIA.

This is required because the validated ADR-044 AMD/TheRock runtime exposes the AMD accelerator through the same CTranslate2 CUDA-facing API.

Physical hardware identity comes from the separate Windows hardware observation.

---

### 8. `auto` is not guessed

If the configured transcription device is:

```text
auto
```

the diagnostic observer does not guess which backend CTranslate2 selected.

Capability observation requiring an explicit CTranslate2 device is reported as unavailable rather than inferring CPU or accelerator state.

---

### 9. Runtime diagnostic snapshots belong to the controller session

`RuntimeProcessHost` retains the latest:

```text
graphics_adapters
transcription_runtime
```

observations.

A fresh Start clears observations from the previous runtime session.

Normal Stop retains observations from the runtime that just stopped.

This allows the expected support workflow:

```text
Start
    ↓
run conversation
    ↓
Stop
    ↓
Create Support Bundle
```

to include the runtime that was actually used.

The first implementation does not persist these snapshots across controller process restarts.

---

### 10. Support-bundle collection consumes snapshots through dependency injection

The support-bundle collector does not depend directly on `RuntimeProcessHost`.

The controller injects a snapshot provider:

```text
RuntimeProcessHost
        ↓
diagnostics snapshot provider
        ↓
DefaultSupportInfoCollector
```

The collector reads one snapshot per collection operation so related diagnostic sections represent the same controller state.

---

### 11. `system-info.json` keeps diagnostic sources visibly separate

Support bundles expose:

```text
distribution
configuration
hardware
transcription_runtime
packages
```

Their meanings are:

```text
distribution
    deterministic application/build identity

configuration
    mutable configured settings

hardware
    operating-system-observed graphics hardware

transcription_runtime
    capabilities reported by the initialized ML runtime

packages
    legacy/best-effort Python environment discovery
```

A missing runtime observation is represented distinctly as:

```text
error_type = NotObserved
```

This is different from a failed observation such as a PowerShell, import, or native-runtime query failure.

---

### 12. Diagnostics contain no transcription content

Runtime hardware/capability snapshots must not include:

```text
audio
transcript text
model input
model output
database rows
conversation content
```

They contain only environment, hardware, configuration, lifecycle, and runtime capability information.

Transcript database inclusion remains an explicit support-bundle choice established by the existing support-bundle architecture.

---

## Resulting Architecture

```text
                    Windows Controller
                           │
                           │ lifecycle + diagnostics IPC
                           ▼
                 RuntimeProcessHost
                           │
             ┌─────────────┴─────────────┐
             │                           │
             ▼                           ▼
        lifecycle state          diagnostic snapshot
                                      │
                                      ├── graphics adapters
                                      └── transcription runtime
                                             │
                                             ▼
                                      Support Bundle
                                             │
                                             ▼
                                      system-info.json


                    Spawned Runtime Child
                           │
                           ▼
                Win32_VideoController
                           │
                           ▼
                  hardware observation
                           │
                           ▼
                  Application.start()
                           │
                           ▼
                configured native runtime
                           │
                           ▼
                    Faster-Whisper
                           │
                           ▼
                     CTranslate2
                           │
                           ▼
            transcription-runtime observation
```

---

## Failure Semantics

Diagnostics are deliberately best-effort.

The following must not fail application startup:

```text
PowerShell unavailable
Win32_VideoController query failure
malformed hardware output
CTranslate2 capability query failure
diagnostic serialization failure at the observer boundary
```

Where possible, diagnostic failures are converted into typed unavailable observations containing:

```text
available = false
error_type
error
```

Application lifecycle failures remain represented separately through the normal runtime failure contract.

---

## Validation

### Unit and process-boundary validation

Tests cover:

- typed hardware observation;
- Windows graphics query parsing;
- diagnostic failure degradation;
- typed CTranslate2 capability observation;
- CPU and accelerator capability queries;
- `auto` without backend guessing;
- IPC transport of hardware observations;
- IPC transport of transcription-runtime observations;
- diagnostic events not changing lifecycle state;
- fresh Start clearing stale runtime observations;
- normal Stop preserving the latest observations;
- diagnostics remaining independent from application startup success;
- support-bundle serialization;
- distinction between `NotObserved` and actual observation failure.

### Real AMD/TheRock acceptance

The implementation was validated on Windows 11 with:

```text
AMD Radeon RX 6800M
driver: 32.0.21045.5002

AMD Radeon(TM) Graphics
driver: 31.0.21925.1001
```

The configured transcription runtime was:

```text
runtime: therock
device: cuda
compute_type: float16
```

After successful application startup, CTranslate2 reported:

```text
cuda_device_count = 1

supported_compute_types:
    bfloat16
    float16
    float32
    int8
    int8_bfloat16
    int8_float16
    int8_float32
```

A Start → Stop → Start → Stop runtime test reproduced the same hardware and transcription-runtime observations in two fresh spawned processes.

Both diagnostic snapshots remained available after normal Stop.

A real support bundle created after Stop contained:

```text
distribution
configuration
hardware
transcription_runtime
packages
```

with the Windows hardware observation and the initialized TheRock/CTranslate2 capability observation preserved in `system-info.json`.

### Final quality gate

```text
ruff:
clean

mypy:
clean

pytest:
624 passed
```

The two existing Python 3.14 `torch.jit.load` deprecation warnings remain known and unrelated.

---

## Consequences

### Positive

- Support bundles distinguish packaged identity, requested configuration, OS-visible hardware, and actual ML-runtime capability.
- The controller remains isolated from native ML/GPU initialization.
- Hardware information can survive later runtime startup failure.
- Runtime capabilities describe the runtime that actually initialized.
- The same model supports CPU, NVIDIA, and AMD/TheRock without vendor-specific controller dependencies.
- Support bundles created after Stop retain useful runtime diagnostics.
- Diagnostic failures do not affect application availability.
- Components remain strongly typed and independently testable.

### Negative

- Additional typed diagnostic events cross the controller/runtime process boundary.
- The controller retains session-scoped diagnostic state.
- PowerShell/CIM is a Windows-specific machine-observation dependency.
- Runtime diagnostic state is currently lost when the controller process itself exits.
- CTranslate2's `cuda` terminology cannot by itself identify GPU vendor and must be interpreted together with the separate hardware observation.

These costs are acceptable because they materially improve remote diagnosability while preserving the process isolation established by ADR-050.

---

## Alternatives Considered

### Infer runtime capability from distribution metadata

Rejected.

Distribution metadata describes what was built, not what the current machine or initialized runtime can use.

### Infer runtime capability from configuration

Rejected.

Configuration describes requested behavior, not successful initialization or hardware visibility.

### Import CTranslate2 directly in the controller

Rejected.

This would allow support diagnostics to initialize or fail native runtime state in the controller process and violate ADR-050 isolation.

### Use vendor-specific NVIDIA/AMD hardware tools

Rejected for the initial machine inventory.

`Win32_VideoController` provides a simple vendor-neutral Windows boundary sufficient for GPU name and driver information.

Vendor-specific diagnostics can be added later only if a concrete support requirement requires them.

### Persist runtime observations to disk

Deferred.

Keeping the latest observation in the controller session is sufficient for the current Start → Stop → Create Support Bundle workflow.

Persistence can be introduced later if support bundles must retain runtime observations across controller restarts.

---

## Related Decisions

- ADR-016 — Application Composition Root
- ADR-017 — Logging Strategy
- ADR-044 — AMD GPU Transcription Runtime and CPU Fallback Strategy
- ADR-049 — Windows End-User Packaging, Runtime Layout and Interactive Control Host
- ADR-050 — Interactive Controller and Transcription Runtime Process Boundary
- ADR-051 — Windows NVIDIA Faster-Whisper Runtime Distribution
- ADR-052 — Deterministic Distribution Metadata for Support Diagnostics
