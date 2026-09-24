# ADR-054: Local Whisper Model Provisioning and Offline Runtime Startup

## Status

Accepted

## Date

2026-09-21

## Context

The application currently configures Faster-Whisper using a logical model name:

```text
tiny
base
small
medium
large-v3
turbo
```

The configured value is passed directly to Faster-Whisper during application composition.

Conceptually:

```text
configuration
    ↓
whisper.model = medium
    ↓
FasterWhisperModelFactory
    ↓
WhisperModel("medium")
```

When the requested model is not already available in the Hugging Face cache, Faster-Whisper resolves and downloads it while constructing the model.

This makes runtime startup implicitly responsible for two very different operations:

```text
model acquisition
+
model initialization
```

A fresh installation can therefore behave as:

```text
User presses Start
        ↓
runtime process starts
        ↓
GPU/CPU runtime initializes
        ↓
Whisper model construction begins
        ↓
external network request
        ↓
potentially large model download
        ↓
model initialization
        ↓
application reports RUNNING
```

This behavior was observed during external Windows acceptance testing after changing:

```yaml
whisper:
  model: medium
```

Several startup attempts failed with:

```text
WinError 10054
```

before a later attempt eventually succeeded.

The support bundle showed startup attempts terminating after native transcription-runtime initialization but before the runtime reported readiness.

The same installation was otherwise capable of initializing its NVIDIA runtime and performing GPU transcription successfully.

The failure therefore demonstrated an important distribution concern:

```text
application startup currently depends on external model availability
```

rather than only on locally installed application resources.

This is undesirable for an end-user Windows application.

The intended distribution experience is:

- installation produces a usable application;
- the default model works without network access;
- pressing Start does not unexpectedly perform a large download;
- optional models can be acquired explicitly;
- interrupted downloads can be retried safely;
- runtime startup consumes an already prepared local model;
- support diagnostics can determine which model is selected and whether it is locally available.

This is especially important because the Windows controller and transcription runtime are intentionally separated by ADR-050.

Model acquisition does not require initializing:

```text
Faster-Whisper
CTranslate2
CUDA
TheRock / HIP
```

and therefore should not be hidden inside the isolated transcription-runtime startup sequence.

---

## Decision

### 1. Model provisioning and model execution are separate responsibilities

The application will distinguish:

```text
model provisioning
```

from:

```text
model execution
```

Model provisioning owns obtaining and validating the files required for a configured Whisper model.

Model execution owns loading an already available local model and performing transcription.

The transcription runtime must not implicitly download a model while transitioning from:

```text
STARTING
```

to:

```text
RUNNING
```

---

### 2. Configuration continues to express a logical model choice

The user-facing configuration remains based on a logical model identifier.

For example:

```yaml
whisper:
  model: small
```

or:

```yaml
whisper:
  model: medium
```

The configuration will not contain a machine-specific absolute path to a downloaded model.

The existing strongly typed `WhisperModel` configuration remains the user-facing source of truth for the selected model.

Conceptually:

```text
whisper.model
    ↓
logical model identifier
    ↓
model resolver
    ↓
local model directory
```

This preserves portable configuration across machines and distribution profiles.

---

### 3. Application-owned model storage will be used

Provisioned models will live under the application runtime root rather than in an implicit third-party cache.

For installed Windows execution, the intended layout is:

```text
%LOCALAPPDATA%\AudioTranscriptionService\
    config\
    data\
    diagnostics\
    logs\
    models\
    support\
```

Conceptually:

```text
models\
    small\
    medium\
    large-v3\
    ...
```

The exact internal directory representation may evolve as an implementation detail.

The important architectural rule is:

```text
the application owns the model location
```

rather than relying on the process-global Hugging Face cache as the runtime contract.

Development execution will use the corresponding application runtime root established by `RuntimePaths`.

---

### 4. The model resolver is an application-owned boundary

A small application-owned model-resolution component will translate:

```text
logical Whisper model
```

into:

```text
validated local model path
```

Conceptually:

```text
WhisperModel.SMALL
        ↓
ModelResolver
        ↓
...\models\small
```

The resolver must not know about:

```text
CUDA
AMD/TheRock
CPU execution
transcription workers
audio capture
language processing
```

Its responsibility is only to determine whether the requested model is locally ready and, when it is, provide its local path.

This keeps model storage replaceable independently from Faster-Whisper execution.

---

### 5. Provisioning will have explicit observable state

A model may be in one of a small number of application-level states.

Conceptually:

```text
NOT_INSTALLED
DOWNLOADING
READY
FAILED
```

An interrupted or incomplete model must never be exposed to the transcription runtime as:

```text
READY
```

Provisioning must therefore complete into temporary/incomplete state and only publish the final model as ready after required files have been successfully obtained and validated.

The exact download implementation and temporary-directory naming are implementation details.

---

### 6. The default `small` model will be available after installation

The Windows end-user distributions will provide the default:

```text
small
```

model as part of the installed product.

A fresh installation using the default configuration must therefore be capable of reaching:

```text
RUNNING
```

without contacting an external model service.

This applies to the supported Windows runtime distributions:

```text
CPU
NVIDIA
AMD
```

unless a future distribution decision explicitly changes the default model.

The model should remain outside the executable's private native-runtime layout so that application upgrades and runtime-profile changes do not unnecessarily couple the model lifecycle to:

```text
CPU runtime binaries
NVIDIA runtime binaries
AMD/TheRock runtime binaries
```

---

### 7. Optional models are provisioned explicitly

Models other than the bundled default may be installed separately.

For example:

```text
medium
large-v3
turbo
```

Changing configuration to such a model does not authorize an invisible download during runtime startup.

Instead, the application must determine whether the selected model is locally ready before launching transcription.

Conceptually:

```text
configured model
        ↓
is READY locally?
      /     \
    yes      no
     │        │
     ▼        ▼
 start     actionable
runtime      state
```

A future controller UI may expose explicit actions such as:

```text
Download model
Retry
Remove model
```

The exact UI is not established by this ADR.

---

### 8. Downloads must be recoverable

Network failure during optional model acquisition is expected to be recoverable.

Examples include:

```text
connection reset
temporary internet loss
remote service interruption
application shutdown
```

Such failures must not corrupt an existing ready model.

A failed provisioning attempt must leave the model in a state from which another provisioning attempt can safely continue or restart.

Retry policy must remain bounded and observable rather than implementing an indefinite hidden startup retry loop.

---

### 9. The transcription runtime receives a local model path

After this decision is implemented, Faster-Whisper construction will conceptually change from:

```text
WhisperModel("medium")
```

to:

```text
WhisperModel(
    "C:\\...\\AudioTranscriptionService\\models\\medium"
)
```

The model factory remains responsible for constructing the concrete Faster-Whisper model.

It is not responsible for:

```text
downloading
retrying downloads
selecting model repositories
managing model installation state
```

This preserves the existing separation between application composition and the concrete transcription adapter.

---

### 10. Runtime startup must be local and deterministic with respect to model acquisition

Once the configured model is in:

```text
READY
```

state, application startup must not require model-network access.

The startup dependency becomes:

```text
configured logical model
        ↓
local model resolver
        ↓
validated local directory
        ↓
Faster-Whisper model construction
        ↓
RUNNING
```

External model services are therefore removed from the normal runtime-startup critical path.

This does not mean the complete application is guaranteed to operate without every possible external dependency forever.

It specifically establishes that:

```text
Whisper model acquisition
```

is not part of transcription runtime startup.

---

### 11. Model provisioning is independent of transcription runtime profile

The logical Whisper model and its files are independent from whether inference executes using:

```text
CPU
NVIDIA CUDA
AMD/TheRock
```

The same locally provisioned model should therefore be reusable when switching compatible application runtime distributions.

Conceptually:

```text
                   ┌── CPU runtime
local small model ─┼── NVIDIA runtime
                   └── AMD runtime
```

Distribution-specific native runtime files remain owned by their existing packaging decisions.

Model storage must not duplicate models merely because the user changes runtime profile.

---

### 12. Support diagnostics will expose model availability

Support diagnostics should eventually distinguish at least:

```text
configured model
resolved local model
provisioning state
```

and, where deterministically available:

```text
model source/repository
model revision/version
```

Support collection must not read or archive model weights.

Support diagnostics must remain useful when the selected model is:

```text
missing
partially downloaded
failed
ready
```

This extends the diagnostic principles established by ADR-052 and ADR-053:

```text
configuration
distribution facts
runtime observations
model provisioning state
```

represent different facts and should remain distinguishable.

---

### 13. Model provisioning must not initialize the transcription runtime

Checking, downloading, or validating model availability must not require importing or initializing:

```text
CTranslate2
CUDA
cuDNN
cuBLAS
AMD/TheRock
```

Model-management behavior must therefore remain usable even when the configured transcription runtime cannot start.

This preserves the controller/runtime isolation established by ADR-050.

---

### 14. Existing transcription behavior remains unchanged

This decision does not change:

```text
audio capture
normalization
VAD
speech segmentation
aggregation
transcription queueing
worker concurrency
adaptive language selection
microphone gain
SQLite persistence
```

Once a Faster-Whisper model has been constructed from its local path, the existing transcription pipeline continues unchanged.

---

## Resulting Architecture

Before:

```text
config.whisper.model
        ↓
FasterWhisperModelFactory
        ↓
WhisperModel(logical_name)
        ↓
third-party cache/network if missing
        ↓
model
```

After:

```text
                    Controller / provisioning
                             │
config.whisper.model ────────┤
                             ▼
                      Model Provisioner
                             │
                             ▼
                  application model store
                             │
                        READY model
                             │
                             ▼
                       Model Resolver
                             │
                     local model path
                             │
                             ▼
                 transcription runtime
                             │
                             ▼
                FasterWhisperModelFactory
                             │
                             ▼
                WhisperModel(local_path)
```

Normal startup after provisioning therefore becomes:

```text
Start
  ↓
resolve configured model locally
  ↓
initialize transcription runtime
  ↓
load local model
  ↓
RUNNING
```

No model download occurs inside this path.

---

## Consequences

### Positive

- Fresh default installations can start without internet access.
- Pressing Start no longer hides a potentially large model download.
- Network failures such as connection resets are separated from transcription-runtime failures.
- Optional downloads can expose progress and actionable errors.
- Download retry behavior can be tested independently.
- Model files survive application/runtime-profile upgrades when appropriate.
- CPU, NVIDIA, and AMD distributions can share the same model store.
- The transcription runtime receives deterministic local resources.
- Support bundles can distinguish missing-model failures from native-runtime failures.
- The controller can manage model availability without initializing native ML runtimes.
- Model-management behavior becomes independently replaceable and testable.

### Negative

- The default Windows installation becomes larger because it includes the `small` model.
- The application becomes responsible for model storage and lifecycle.
- Additional implementation is required for provisioning, validation, retry, and cleanup.
- Optional model downloads require controller/user experience beyond editing configuration.
- Packaging must stage the default model in addition to application/runtime binaries.
- Model source and revision metadata must be managed deterministically enough for diagnostics.

These costs are acceptable because deterministic end-user startup is more important than minimizing installer size.

---

## Alternatives Considered

### Keep Faster-Whisper's implicit download behavior

Rejected.

This keeps implementation simple but makes:

```text
Start
```

potentially perform a long external network operation.

It also mixes network/provisioning failures with transcription-runtime startup failures.

External Windows acceptance demonstrated that this produces poor failure behavior for nontechnical users.

---

### Retry downloads automatically inside runtime startup

Rejected.

Retries could hide temporary failures but would preserve the incorrect ownership boundary.

Runtime startup would still depend on:

```text
network availability
remote service availability
download duration
```

and the controller would have poor visibility into progress.

---

### Use the Hugging Face global cache as the application model store

Rejected as the runtime contract.

Third-party caching may still be used internally by a provisioning implementation where useful, but application correctness must not depend on an implicit machine-global cache location.

The application needs deterministic ownership and diagnosability of its installed models.

---

### Bundle every supported model

Rejected.

Models such as:

```text
medium
large-v3
```

would unnecessarily increase the distribution size for users who never use them.

Only the default model must be available immediately.

Additional models remain optional.

---

### Require users to manually download and configure model paths

Rejected.

This would simplify application implementation at the cost of the end-user experience.

The Windows distribution is explicitly intended to be usable by nontechnical users.

---

### Store model files inside each packaged runtime distribution

Rejected.

This would unnecessarily couple identical model data to:

```text
CPU
NVIDIA
AMD
```

distribution variants and could duplicate large model files when switching distributions.

Models belong to mutable application-owned runtime data.

---

## Testing Requirements

### Unit tests

Tests must cover at least:

```text
logical model → local path resolution
missing model
ready model
incomplete model
failed provisioning state
successful publication of a completed model
existing ready model not being corrupted by failed provisioning
runtime receiving a local path rather than a logical model name
```

Model-management tests must not require:

```text
GPU hardware
CTranslate2 initialization
real audio hardware
```

---

### Integration tests

Integration coverage should verify:

```text
provisioned local Faster-Whisper model can be loaded
configured model resolution reaches the expected local model
runtime startup does not initiate model downloading
```

Network-dependent provisioning integration tests should remain separate from normal application startup tests.

---

### Packaged Windows acceptance

Each Windows runtime profile must eventually verify:

```text
fresh installation
default small model present
network unavailable
Start
RUNNING
real transcription
Stop
```

Optional-model acceptance should verify:

```text
medium not installed
explicit provisioning
download interruption/failure
retry
medium READY
Start
RUNNING
restart
no additional model download
```

Support-bundle acceptance should verify that model provisioning information is visible without including model contents.

---

## Implementation Strategy

Implementation will proceed incrementally.

### Slice 1 — Runtime model storage boundary

Introduce:

```text
models_directory
```

into the application's runtime paths and establish deterministic local model path resolution.

No downloading behavior changes yet.

### Slice 2 — Local model resolver

Introduce a strongly typed resolver that maps the configured logical model to its application-owned local path and identifies whether it is ready.

Keep this independent from Faster-Whisper.

### Slice 3 — Runtime consumes resolved local path

Change composition so `FasterWhisperModelFactory` receives the resolved local path rather than the logical model name.

At this point implicit model downloading during application startup is eliminated.

### Slice 4 — Model provisioning

Introduce explicit model acquisition with observable:

```text
NOT_INSTALLED
DOWNLOADING
READY
FAILED
```

state and safe failure/retry semantics.

### Slice 5 — Controller integration

Expose selected-model availability before runtime startup and provide actionable behavior when an optional configured model is missing.

### Slice 6 — Default model packaging

Stage the default `small` model into Windows CPU, NVIDIA, and AMD installation artifacts and install it into the application-owned model directory.

### Slice 7 — Support diagnostics

Include non-sensitive model-provisioning state in support bundles.

### Slice 8 — Packaged acceptance

Validate fresh offline startup and optional-model download/retry behavior on external Windows systems.

---

## Implementation status

Implemented and acceptance-tested on Windows.

The application now separates Whisper model provisioning from runtime
execution.

Configured model names are resolved through the application-owned model
directory:

`<runtime-root>/models/<model>/`

A model is considered published only when its contents are valid and the
`.ready` marker exists.

Runtime startup resolves the configured logical model to a local path before
constructing Faster-Whisper. Runtime startup does not download models and does
not depend on network access.

The controller exposes the provisioning states:

- `NOT_INSTALLED`
- `DOWNLOADING`
- `READY`
- `FAILED`

Users can install missing models and retry failed provisioning attempts from
the controller. Provisioning runs outside the Tk UI thread.

Support diagnostics include the configured model, resolved local path,
provisioning state, and failure message when applicable. Provisioning start,
success, and failure are recorded in application logs.

The Windows CPU, NVIDIA, and AMD installers seed the default `small` model from
a validated build artifact into the application-owned model directory when the
directory does not already exist. Existing model data is preserved on reinstall
and uninstall.

Acceptance testing validated:

- explicit provisioning from `NOT_INSTALLED` to `READY`;
- offline runtime startup from an already provisioned model;
- deterministic failure when a configured model is absent;
- failed network provisioning followed by successful retry;
- persisted `READY` state across controller restarts;
- support-bundle model diagnostics;
- fresh-install model seeding for CPU, NVIDIA, and AMD installers;
- preservation of existing model data during reinstall;
- preservation of model data during uninstall.

---

## Related Decisions

- ADR-005 — Architectural Boundaries
- ADR-011 — Typed Configuration System
- ADR-013 — Configuration Model Design
- ADR-016 — Application Composition Root
- ADR-030 — Transcription Boundary and Faster-Whisper Adapter
- ADR-042 — Concurrent Transcription Execution with Multiple Whisper Workers
- ADR-044 — AMD GPU Transcription Runtime and CPU Fallback Strategy
- ADR-049 — Windows End-User Packaging, Runtime Layout and Interactive Control Host
- ADR-050 — Interactive Controller and Transcription Runtime Process Boundary
- ADR-051 — Windows NVIDIA Faster-Whisper Runtime Distribution
- ADR-052 — Deterministic Distribution Metadata for Support Diagnostics
- ADR-053 — Runtime-Observed Hardware and Transcription Diagnostics Across the Controller Process Boundary