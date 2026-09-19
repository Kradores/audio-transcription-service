# ADR-053: Runtime-Observed Hardware and Transcription Diagnostics Across the Controller Process Boundary

## Status

Accepted

## Date

2026-09-18

## Context

ADR-049 introduced the Windows end-user distribution and support-bundle workflow.

ADR-050 separated the interactive controller from the transcription runtime using a fresh child process and lightweight local lifecycle IPC.

ADR-051 introduced independent CPU and NVIDIA Windows distributions and retained the existing AMD/TheRock runtime architecture.

ADR-052 introduced deterministic distribution metadata so support diagnostics can reliably describe the built artifact without relying on mutable configuration or Python package discovery inside PyInstaller.

ADR-052 intentionally separated deterministic artifact metadata from runtime-observed information.

The support bundle can now reliably answer:

```text
what application artifact was built?
what dependency versions were packaged?
what accelerator libraries were packaged?
what configuration is currently selected?
```

It cannot yet reliably answer:

```text
what graphics hardware does this machine expose?
what graphics driver is installed?
did the configured transcription backend initialize successfully?
how many accelerator devices can CTranslate2 see?
what compute types does CTranslate2 report on this machine?
```

These facts are machine/runtime observations rather than build facts.

The controller must remain isolated from transcription-native dependencies. Support-bundle creation must not cause the controller to import or initialize:

```text
Faster-Whisper
CTranslate2
CUDA
TheRock / HIP
ROCm
```

because doing so would weaken the runtime failure isolation established by ADR-050 and ADR-052.

## Decision

Runtime-observed diagnostics will be collected inside the spawned transcription-runtime process and communicated to the controller through the existing local runtime status channel.

The controller will store immutable snapshots of the most recent observations and expose them to support-bundle collection.

No network API, external service, shared global state, or direct controller access to transcription objects will be introduced.

### Machine and transcription observations remain separate

Runtime diagnostics will distinguish:

```text
machine observation
    → characteristics of the Windows machine

transcription-runtime observation
    → characteristics of the initialized ML runtime
```

Machine observation will initially include Windows graphics adapters.

Conceptually:

```text
graphics adapters
    name
    driver version
    PNP device ID
```

Transcription-runtime observation will initially include:

```text
configured runtime
configured device
configured compute type
successful runtime/application startup
CTranslate2 visible CUDA device count
CTranslate2 supported compute types
```

The two observations must not be conflated.

For example, a machine may contain an NVIDIA GPU while the application is intentionally running with:

```text
runtime = default
device = cpu
```

That state is valid and must remain observable.

### Windows graphics information will use OS-level inventory

The initial Windows implementation will use `Win32_VideoController` data.

It will report all discovered graphics adapters rather than trying to guess which adapter CTranslate2 selected.

The initial fields will be:

```text
name
driver_version
pnp_device_id
```

No NVIDIA-only dependency will be introduced merely to discover graphics hardware.

This keeps the machine observation usable for:

```text
CPU systems
NVIDIA systems
AMD systems
hybrid laptops
```

### Machine observation occurs in the runtime child

The runtime child will perform the Windows graphics-adapter query before application startup.

It will publish the result using a small diagnostic runtime-process event.

Conceptually:

```text
RuntimeEnvironmentEvent
    ↓
RuntimeProcessHost
    ↓
latest environment observation
```

Machine-observation failure must not prevent application startup.

Failures will produce structured unavailable/error information.

### Transcription-runtime observation occurs after successful startup

CTranslate2 runtime observation will only happen after the application has successfully completed startup.

At that point the configured runtime initializer and model construction have already succeeded.

The observer may dynamically access the already initialized CTranslate2 runtime.

The initial CTranslate2 observations will use:

```text
get_cuda_device_count()
get_supported_compute_types()
```

GPU-specific queries will only be performed where relevant to the configured device.

### Runtime observations are diagnostic only

Observation failures must never change functional runtime behavior.

A failure to discover:

```text
graphics adapters
driver version
CTranslate2 capabilities
```

must not:

```text
fail application startup
stop transcription
change runtime selection
cause CPU fallback
change device selection
```

Diagnostic failures will be recorded as unavailable/error information.

### Runtime observations cross the existing IPC boundary

The existing multiprocessing status queue will remain the communication mechanism.

The runtime-process event contract will be extended with small strongly typed diagnostic values.

No transcript content, captured audio, models, application objects, or large payloads will cross this channel.

The channel remains strictly operational.

### RuntimeProcessHost owns the latest observation snapshot

`RuntimeProcessHost` will retain the latest machine and transcription-runtime observations.

Starting a new runtime process clears previous runtime observations before the new attempt begins.

This prevents diagnostics from a previous runtime session from being mistaken for observations from the current attempt.

After a successfully started runtime stops normally, its most recent observations may remain available while the same controller remains open so a support bundle can be created after Stop.

No persistent runtime-observation cache will be introduced initially.

If the controller itself is restarted, old runtime observations are discarded.

Persistent diagnostic snapshots may be considered later if real support experience demonstrates a need.

### Support bundles consume snapshots through dependency injection

The support-bundle collector will not know how observations are produced.

It will receive a small provider/callable capable of returning the controller's current runtime-process diagnostic snapshot.

Conceptually:

```text
RuntimeProcessHost
        ↓
snapshot provider
        ↓
DefaultSupportInfoCollector
        ↓
system-info.json
```

This keeps support diagnostics testable and independent from multiprocessing implementation details.

### Support information will preserve source semantics

The resulting support bundle will continue to distinguish:

```text
distribution
    immutable build facts

configuration
    mutable requested behavior

hardware
    machine-observed facts

transcription_runtime
    runtime-observed facts

packages
    best-effort Python metadata discovery
```

No source will silently override another.

### AMD compatibility is a design requirement

The runtime-observation contract must not assume that `"cuda"` means NVIDIA.

The existing TheRock CTranslate2 backend also exposes its accelerator through CTranslate2's CUDA-facing APIs.

Therefore the CTranslate2 diagnostic abstraction will remain backend-neutral.

Future AMD gfx1031 packaging should be able to reuse the same runtime observation contract while adding AMD-specific information only where necessary.

### No persistence initially

Runtime observations will remain controller-session state.

We will not introduce:

```text
runtime-observation.json
diagnostic database tables
registry persistence
```

until there is evidence that cross-controller-session persistence is useful.

This avoids stale diagnostic data and keeps the first implementation small.

## Failure semantics

Machine observation failure produces:

```text
hardware.graphics_adapters.available = false
```

plus a bounded diagnostic error.

Application startup continues.

CTranslate2 observation failure after successful application startup produces:

```text
transcription_runtime.available = false
```

plus a bounded diagnostic error.

The runtime still reports `RUNNING`.

Actual transcription-runtime initialization failure remains an application startup failure and continues to produce the existing:

```text
STARTING → FAILED
```

controller transition.

Diagnostics must not hide or reinterpret that failure.

## Privacy

Runtime diagnostic events must not contain:

```text
transcript text
captured audio
model input
model output
database contents
user documents
```

Hardware names, driver versions, runtime versions, device counts, process identifiers, and compute capabilities are acceptable operational diagnostic information.

## Testing

Focused tests should prove the Windows graphics observer parses zero, one, and multiple adapters; malformed/failed OS queries degrade gracefully; CTranslate2 observation handles CPU and accelerator devices; supported compute types are sorted deterministically; diagnostic failure does not fail application startup; multiprocessing transports observations correctly; `RuntimeProcessHost` clears observations on a fresh Start; observations remain available after normal Stop; failed startup never reuses an earlier runtime observation; and support bundles serialize the observations without loading ML dependencies in the controller.

Real Windows acceptance should validate both CPU and NVIDIA packaged applications.

NVIDIA acceptance should confirm a real RTX GPU name and driver version, CTranslate2 GPU count, and `float16` support.

AMD gfx1031 acceptance will be added when the AMD packaged build/installer milestone is implemented.

## Consequences

The positive consequence is much stronger remote diagnosability without breaking controller/runtime isolation. The same high-level diagnostic contract can serve CPU, NVIDIA, and future AMD packages.

The cost is a slightly richer controller/runtime IPC contract and additional session state in `RuntimeProcessHost`.

Those costs are preferable to loading native ML dependencies in the controller or inferring runtime behavior from logs/configuration.

## Alternatives considered

Query CTranslate2 directly from the controller was rejected because it would weaken native-runtime failure isolation.

Using NVIDIA NVML as the sole hardware inventory was rejected because it would make generic machine diagnostics vendor-specific and would not serve AMD systems.

Parsing application logs was rejected because structured state should not be reconstructed from human-oriented log messages.

Persisting runtime observations immediately to disk was deferred because no current requirement justifies stale-state handling and lifecycle complexity.

Inferring GPU/runtime state from the distribution profile was rejected because build identity does not prove hardware availability or successful runtime initialization.

## Documentation impact

`architecture.md` should show runtime-observed diagnostics crossing the child-process boundary.

`observability.md` should define the semantics of `hardware` and `transcription_runtime`.

`testing.md` should document the focused IPC/observer tests and packaged acceptance.

`changelog.md` should record the feature once implemented.

`deployment.md` only needs a small note if packaged acceptance exposes distribution-specific behavior.
