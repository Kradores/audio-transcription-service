# ADR-044: AMD GPU Transcription Runtime and CPU Fallback Strategy

## Status

Accepted — implemented and validated on real Windows AMD hardware.

## Context

The service originally executed Faster-Whisper transcription on CPU.

Real-conversation benchmarking established a useful CPU operating point with:

```text
worker_count = 2
```

but transcription remained the most compute-intensive part of the local
two-sided conversation pipeline.

The target development machine also contains:

```text
AMD Radeon RX 6800M
RDNA2
gfx1031
approximately 12 GB VRAM
```

The project therefore investigated whether Faster-Whisper could be accelerated
locally on AMD GPU hardware without introducing cloud dependencies or coupling
the complete application to one GPU runtime.

Faster-Whisper executes inference through CTranslate2.

CTranslate2 exposes its HIP backend through the existing:

```text
device = "cuda"
```

identifier.

The application must therefore distinguish:

```text
application runtime selection
```

from:

```text
CTranslate2 device naming
```

and must not invent an unsupported `rocm` CTranslate2 device value.

### Official ROCm Windows attempt

An initial environment using the official ROCm 7.2.1 Windows packages and
CTranslate2 4.8.1 did not provide a reliable runtime.

CTranslate2 GPU discovery crashed inside:

```text
amdhip64_7.dll
```

with a native access violation.

This path was rejected for the target environment.

### TheRock investigation

The AMD TheRock Windows runtime successfully exposed the discrete GPU:

```text
device 0
gfx1031
20 compute units
approximately 11.98 GB device memory
```

The validated packages are pinned to:

```text
rocm==10.1.0a20260829
rocm-sdk-core==10.1.0a20260829
rocm-sdk-devel==10.1.0a20260829
rocm-sdk-device-gfx1031==10.1.0a20260829
rocm-sdk-libraries==10.1.0a20260829
```

from the configured TheRock nightly package index.

TheRock native libraries must be initialized before CTranslate2 or
Faster-Whisper is imported.

The validated bootstrap is conceptually:

```python
import rocm_sdk

rocm_sdk.initialize_process(
    preload_shortnames=[
        "amd_comgr",
        "amdhip64",
        "hipblas",
        "hiprand",
    ]
)

# CTranslate2 / Faster-Whisper imports happen only afterwards.
```

This ordering is a runtime requirement rather than an incidental implementation
detail.

### CTranslate2 shutdown deadlock

A custom HIP-enabled CTranslate2 4.8.1 build initially passed short inference
tests but the real application could deadlock during shutdown after sustained
use.

WinDbg analysis showed the process waiting while CTranslate2 worker teardown
entered the non-OpenMP fallback thread-pool path.

The build had:

```text
OPENMP_RUNTIME=NONE
```

and therefore compiled the `_OPENMP`-disabled implementation in
`src/cpu/parallel.cc`.

That implementation uses a thread-local `BS::thread_pool`.

During Windows worker-thread shutdown, destruction of that thread-local pool
could attempt to join nested worker threads while the loader was shutting down
the parent thread.

The outer CTranslate2 pool then waited indefinitely for the stuck worker.

This produced the observed application shutdown deadlock.

The selected fix is to compile CTranslate2 with Intel OpenMP instead of the
fallback thread pool.

The validated OpenMP runtime is Intel oneAPI 2026.1.

The native CTranslate2 build therefore requires:

```text
WITH_HIP=ON
WITH_CUDA=OFF
WITH_CUDNN=OFF

HIP architecture=gfx1031

OPENMP_RUNTIME=INTEL
OpenMP CXX flag=-fopenmp=libomp
```

with the validated Intel OpenMP import library, header, and runtime DLL.

The custom wheel packages:

```text
ctranslate2.dll
libiomp5md.dll
```

with the Python CTranslate2 package.

### Hybrid application runtime

The application does not need GPU-enabled PyTorch.

The validated application runtime is deliberately hybrid:

```text
Silero VAD
    ↓
PyTorch CPU
    ↓
CPU

Faster-Whisper
    ↓
CTranslate2
    ↓
TheRock / HIP
    ↓
AMD GPU
```

The known-good Silero runtime uses:

```text
torch==2.13.0+cpu
torchaudio==2.11.0+cpu
```

GPU acceleration is therefore a transcription-backend concern, not a
process-wide machine-learning-runtime choice.

## Decision

### Explicit Whisper runtime selection

Whisper configuration exposes an application-owned runtime selection.

The supported runtime modes are:

```text
default
therock
```

`default` uses the ordinary CPU transcription runtime.

The validated CPU configuration is:

```text
device=cpu
compute_type=int8
worker_count=2
```

`therock` selects the AMD/TheRock transcription runtime.

The validated AMD configuration is:

```text
runtime=therock
device=cuda
compute_type=float16
worker_count=1
```

`cuda` remains the CTranslate2 API identifier for the HIP backend.

No application-level `rocm` CTranslate2 device value is introduced.

### Runtime initialization boundary

Backend-specific process initialization is represented through an explicit
runtime-initializer boundary.

The normal runtime uses a no-op initializer.

The TheRock runtime uses a dedicated initializer that loads and initializes
the required AMD native runtime before Faster-Whisper/CTranslate2 imports.

The dependency ordering is:

```text
runtime selected
        ↓
runtime initializer
        ↓
TheRock native libraries initialized
        ↓
delayed CTranslate2/Faster-Whisper import
        ↓
shared Whisper model created
        ↓
TranscriptionExecutor workers use worker-local wrappers
```

Runtime initialization does not belong inside the transcriber because importing
or constructing the backend there is already too late.

It is also not performed unconditionally in `main` because that would leak one
backend's native requirements into unrelated runtime modes.

### Shared model and worker policy

The existing executor ownership model remains:

```text
one shared Faster-Whisper model
        ↓
worker-local transcriber wrappers
```

CPU and AMD runtimes may use different worker-count defaults because they have
different measured resource characteristics.

The validated defaults are:

```text
CPU:
worker_count=2

AMD/TheRock:
worker_count=1
```

One AMD worker provided enough throughput during the real application
acceptance test and avoids unnecessary concurrent GPU pressure.

### Failure and fallback policy

An explicitly configured:

```text
runtime=therock
```

means that TheRock is required.

If:

- TheRock packages are unavailable;
- a required native library cannot be loaded;
- the configured GPU is unsupported or unavailable;
- CTranslate2 cannot initialize the GPU backend;
- the Faster-Whisper model cannot be created on that backend;

application startup fails clearly.

The application must not silently continue on CPU.

Silent fallback is rejected because it would:

- hide deployment problems;
- make operators believe GPU acceleration is active when it is not;
- materially change performance;
- invalidate runtime-specific worker-count assumptions;
- make configuration behavior nondeterministic.

Automatic accelerator detection may be considered later for:

```text
runtime=default
```

but is not part of this decision.

### Supported hardware scope

The currently validated AMD native artifact targets:

```text
gfx1031
AMD Radeon RX 6800M
Windows x86_64
Python 3.14.6
```

Support for another AMD GPU architecture is not assumed.

Adding another architecture requires:

- the corresponding pinned TheRock device package;
- a CTranslate2 build for that architecture;
- runtime smoke validation;
- sustained teardown validation;
- real application acceptance.

### Reproducible native/runtime preparation

The AMD environment is not assembled manually.

`scripts/amd/toolchain.json` records the required native/runtime contract,
including:

- CTranslate2 version and exact source revision;
- TheRock package versions;
- target GPU architecture;
- Intel OpenMP artifacts;
- required upstream hashes;
- reference build artifacts;
- observed compiler/build-tool versions.

CTranslate2 is pinned to:

```text
version:
4.8.1

source commit:
0d8bcd362ac75ef860ef161d6f0efad0ae439ff0
```

The Intel OpenMP runtime DLL is hash validated.

The script-produced CTranslate2 native DLL used for runtime acceptance has:

```text
SHA256:
BB79CF683495CDC02BFB076549396B810CAFFECA1572E4C08AD2BEE842048188
```

The complete AMD preparation has one normal developer entry point:

```powershell
.\scripts\amd\prepare.ps1
```

The remaining scripts are executable implementation stages used by the entry
point or directly during debugging.

Developers are not expected to infer and manually execute every script in the
directory.

The normal CPU `.venv` remains isolated from the AMD environment.

## Rationale

The design keeps accelerator-specific behavior behind the existing
transcription boundary.

The application remains able to replace:

- Faster-Whisper;
- CTranslate2;
- TheRock;
- the GPU backend;

without changing audio capture, VAD, segmentation, persistence, or the
transcription-executor contract.

Keeping Silero on CPU avoids introducing an unnecessary GPU-enabled PyTorch
runtime and keeps the native AMD dependency surface narrow.

Explicit runtime selection makes failures deterministic and observable.

The custom CTranslate2 build is reproducible because source revision, toolchain
inputs, OpenMP artifacts, target architecture, packaging, and runtime
acceptance are scripted rather than relying on undocumented manual machine
state.

## Consequences

Positive:

- Faster-Whisper can use the RX 6800M GPU locally on Windows.
- The service remains fully local.
- CPU operation remains independent from the AMD runtime.
- Silero VAD remains on the smaller CPU PyTorch runtime.
- GPU-specific initialization is isolated behind a replaceable boundary.
- Native import ordering is explicit.
- CTranslate2's existing device API is preserved.
- The shutdown deadlock caused by the non-OpenMP fallback path is removed from
  the validated build.
- AMD setup is reproducible rather than a sequence of undocumented manual
  commands.
- A single `prepare.ps1` entry point makes the expected developer workflow
  explicit.
- Explicit `therock` configuration cannot silently degrade to CPU operation.

Negative:

- AMD support requires a custom CTranslate2 Windows wheel.
- Native build tooling is more complex than the normal CPU environment.
- Intel OpenMP becomes part of the validated CTranslate2 runtime.
- TheRock packages are pinned to a tested build.
- The current artifact is architecture-specific to `gfx1031`.
- CPU and AMD configurations have different validated worker counts.
- Updating CTranslate2, TheRock, Python, Intel OpenMP, or the target GPU
  architecture requires repeating native and application acceptance testing.

## Alternatives considered

**Continue CPU-only transcription**

Rejected as the only runtime.

CPU remains supported, but the AMD GPU demonstrated materially higher
transcription throughput with substantially lower queue pressure.

**Use the official ROCm 7.2.1 Windows runtime**

Rejected for the target environment.

The tested configuration crashed inside `amdhip64_7.dll` during CTranslate2 GPU
interaction.

**Use `device="rocm"`**

Rejected.

CTranslate2 exposes the HIP backend through the existing `cuda` device
identifier.

The application should not invent a value unsupported by the dependency API.

**Initialize TheRock unconditionally in application startup**

Rejected.

It would couple ordinary CPU execution to AMD-specific native dependencies.

**Initialize TheRock from the transcriber**

Rejected.

Native initialization must happen before importing CTranslate2/Faster-Whisper,
which makes the transcriber too late in the lifecycle.

**Use GPU-enabled PyTorch for Silero VAD**

Rejected.

Silero operates successfully using CPU PyTorch and does not justify broadening
the AMD native runtime surface.

**Build CTranslate2 with `OPENMP_RUNTIME=NONE`**

Rejected.

Sustained real-application testing demonstrated a shutdown deadlock and native
debugging identified the fallback thread-pool lifecycle as the relevant path.

**Use the first allocator experiment as the shutdown fix**

Rejected.

The allocator change did not fix the deadlock and materially worsened inference
latency.

**Silently fall back from `therock` to CPU**

Rejected.

An explicit accelerator configuration must either provide that accelerator or
fail startup clearly.

**Require developers to execute all AMD scripts manually**

Rejected.

The individual scripts remain useful implementation stages, but their
dependency ordering should not be part of developer tribal knowledge.

`prepare.ps1` provides the normal orchestration boundary.

## Testing requirements

Native preparation must verify:

- pinned CTranslate2 source revision;
- clean expected source state;
- required TheRock packages;
- `gfx1031` target architecture;
- Intel OpenMP artifacts and hashes;
- HIP enabled;
- CUDA and cuDNN disabled;
- Intel OpenMP enabled;
- expected native DLL dependencies;
- absence of CUDA/cuDNN native dependencies.

Wheel validation must verify that the produced wheel contains:

```text
CTranslate2 Python extension
ctranslate2.dll
libiomp5md.dll
```

Fresh-runtime validation must verify:

- exact script-produced CTranslate2 DLL is loaded;
- TheRock process initialization succeeds before CTranslate2 import;
- at least one GPU is visible;
- `float16` is supported;
- Faster-Whisper creates the model on the GPU;
- a real audio fixture produces a non-empty transcription;
- model destruction completes;
- the Python process exits successfully.

Sustained validation must:

- retain one Faster-Whisper model across repeated GPU inference;
- run for a meaningful duration;
- destroy the model afterwards;
- fail on teardown timeout or process-exit timeout.

Real application acceptance must exercise:

```text
system_audio
+
microphone
+
CPU Silero VAD
+
per-source aggregation
+
shared TranscriptionExecutor
+
AMD Faster-Whisper
+
SQLite persistence
+
graceful shutdown
```

and verify:

- no unexpected capture-frame drops;
- source identity is preserved;
- accepted work drains;
- executor failures remain zero;
- application shutdown reaches executor termination;
- process teardown returns to the caller.

## Implementation validation

The scripted wheel/runtime path was validated in a completely fresh isolated
environment.

The runtime smoke test verified:

```text
CTranslate2 version = 4.8.1
GPU count = 1
float16 support = yes
real Faster-Whisper inference = successful
model destruction = successful
process exit code = 0
```

The exact loaded CTranslate2 native DLL had:

```text
SHA256:
BB79CF683495CDC02BFB076549396B810CAFFECA1572E4C08AD2BEE842048188
```

### Sustained teardown regression

A 20-minute sustained workload completed:

```text
transcriptions = 1039
duration = 1200.3 seconds
average inference = 1.155 seconds
maximum inference = 1.633 seconds
model destruction = 0.044 seconds
process exit code = 0
```

The previous sustained-use shutdown deadlock did not reproduce.

### Complete application acceptance

The isolated runtime was extended with the complete application dependencies.

Silero was verified as:

```text
torch = 2.13.0+cpu
torchaudio = 2.11.0+cpu
HIP PyTorch = no
CUDA PyTorch = no
```

The application was then exercised with both real audio sources.

Final capture statistics included:

```text
system_audio:
frames_dropped=0
segments_rejected=0

microphone:
frames_dropped=0
segments_rejected=0
```

The AMD transcription executor completed:

```text
worker_count=1
max_active_workers=1
submitted=166
completed=166
rejected=0
failed=0
queue_high_water_mark=2
avg_queue_wait=0.191
```

During shutdown, the final pending transcription was completed and persisted
before the worker terminated.

The observed shutdown sequence reached:

```text
Application shutdown requested
        ↓
both capture paths stopped
        ↓
both speech pipelines stopped
        ↓
remaining accepted transcription completed
        ↓
transcript persisted
        ↓
transcription worker stopped
        ↓
transcription executor stopped
        ↓
conversation pipeline stopped
        ↓
process returned normally
```

The AMD investigation and integration are therefore considered complete for
the currently supported `gfx1031` environment.