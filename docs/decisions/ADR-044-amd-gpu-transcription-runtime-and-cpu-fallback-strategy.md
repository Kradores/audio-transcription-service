# ADR-044 draft

**File when we eventually add it:** `docs/decisions/ADR-044-amd-gpu-transcription-runtime-and-cpu-fallback-strategy.md`

## Status

Proposed — runtime feasibility and OpenMP teardown fix validated; final CPU fallback behavior pending reproducible packaging work.

## Context

Faster-Whisper currently uses CTranslate2 behind the application-owned transcription boundary.

The existing application configuration exposes model, device and compute type. The composition root constructs one shared Faster-Whisper model and worker-local `FasterWhisperTranscriber` adapters. 

AMD GPU feasibility was evaluated on a Radeon RX 6800M (`gfx1031`).

The stock Windows CTranslate2 distribution does not provide the required AMD HIP runtime path. A working runtime was established using:

```text
AMD TheRock runtime
+
custom CTranslate2 4.8.1 HIP build targeting gfx1031
+
Faster-Whisper
```

CTranslate2's HIP backend continues to expose the device through the `"cuda"` device name.

The validated GPU configuration delivered approximately:

```text
18.2 s fixture

CPU INT8:
    ~4.496 s
    ~4.05x realtime

AMD GPU FP16:
    ~1.103 s
    ~16.51x realtime
```

One GPU worker was sufficient during long real two-sided conversations without transcription rejection.

During extended runtime testing, the original custom CTranslate2 build repeatedly deadlocked during shutdown.

WinDbg identified the blocked path as CTranslate2 worker teardown involving the non-OpenMP thread-local `BS::thread_pool`.

Rebuilding CTranslate2 with:

```text
OPENMP_RUNTIME=INTEL
```

removed that fallback thread-pool path.

The resulting native library links:

```text
amdhip64_7.dll
hipblas.dll
libiomp5md.dll
```

and subsequently passed:

```text
short explicit model destruction
Silero/PyTorch coexistence
production import ordering
real long-running conversation shutdown
fixture performance benchmark
```

without reproducing the shutdown deadlock.

TheRock initialization must occur before Faster-Whisper imports CTranslate2. Therefore the existing module-level Faster-Whisper import in composition is incompatible with the AMD runtime.

## Decision

The application will support AMD GPU Faster-Whisper execution as a distinct native runtime configuration.

The application will distinguish:

```text
Faster-Whisper runtime
```

from:

```text
CTranslate2 device
```

so an AMD configuration can explicitly represent:

```yaml
runtime: therock
device: cuda
```

while CPU and stock CUDA installations can use the default runtime.

A dedicated `FasterWhisperModelFactory` will own model construction.

Runtime preparation will occur before Faster-Whisper/CTranslate2 is imported.

Backend-specific initialization will not be placed inside `FasterWhisperTranscriber`.

`FasterWhisperTranscriber` remains an application adapter around an already-created model and remains independently testable with fake model implementations.

TheRock initialization will be encapsulated behind a Faster-Whisper runtime-initialization boundary rather than performed by the application entry point.

The AMD CTranslate2 build used on Windows must use OpenMP rather than CTranslate2's non-OpenMP fallback thread pool. The validated initial runtime is Intel OpenMP.

The application will not silently interpret every transcription/runtime initialization error as permission to fall back to CPU.

CPU fallback semantics will distinguish at minimum:

```text
GPU unavailable after usable runtime initialization
```

from:

```text
required native runtime unavailable or broken
```

A missing or invalid required native runtime is considered a deployment/startup failure unless a separately validated CPU-capable runtime can be loaded safely.

The exact supported fallback matrix will be finalized during the reproducible packaging phase before ADR-044 is marked implemented.

## Consequences

**Positive**

- AMD-specific process initialization stays out of generic transcription contracts.
- Faster-Whisper imports occur only after their required native runtime is prepared.
- CPU, stock CUDA and AMD HIP configurations remain conceptually distinct.
- `FasterWhisperTranscriber` remains simple and highly testable.
- Native-runtime failures become explicit and observable.
- Future runtime implementations can be substituted without changing executor or speech-pipeline architecture.
- The known Windows CT2 shutdown deadlock is avoided by the validated OpenMP build.
- GPU throughput is approximately four times the measured CPU baseline without regression from the OpenMP fix.

**Negative**

- AMD support requires a custom native CTranslate2 build and non-standard runtime packaging.
- TheRock and Intel OpenMP add deployment complexity.
- CTranslate2's `"cuda"` naming for HIP means application configuration needs an explicit runtime concept to avoid ambiguity.
- CPU fallback cannot safely be treated as a universal `try/except` behavior.
- AMD GPU support requires additional integration, native-runtime and long-run regression testing.

## Alternatives considered

**Initialize TheRock in `FasterWhisperTranscriber` — rejected.**

CTranslate2 is imported before the adapter can be constructed, so initialization would occur too late. It would also mix process-runtime ownership with transcription behavior.

**Initialize TheRock unconditionally in `main.py` — rejected.**

TheRock is a Faster-Whisper backend requirement, not a general application dependency. CPU or replacement transcribers should not require AMD runtime knowledge.

**Keep module-level `from faster_whisper import WhisperModel` — rejected.**

It prevents runtime preparation before CTranslate2 native loading.

**Treat `device: cuda` as meaning AMD/TheRock — rejected.**

The same device string is also valid for stock NVIDIA CTranslate2. Runtime and device are different concerns.

**Automatically catch all AMD initialization failures and use CPU — rejected initially.**

Some failures occur before the HIP-enabled CTranslate2 library can safely load at all. Such failures should not be hidden as ordinary GPU unavailability.

**Keep `OPENMP_RUNTIME=NONE` — rejected.**

Extended real workloads reproduced a deterministic native teardown deadlock associated with CTranslate2's fallback thread-local `BS::thread_pool`.

## Testing requirements

ADR-044 requires:

```text
configuration validation
runtime initializer unit tests
factory ordering tests
CPU startup/integration tests
AMD runtime smoke test
real Faster-Whisper GPU integration test
explicit model destruction test
PyTorch/Silero coexistence test
normal python -m app AMD startup
long-running real conversation
shutdown/VRAM release validation
fixture performance benchmark
fallback behavior tests once finalized
```

## Observability requirements

Startup must make the selected transcription runtime and effective execution configuration observable without relying on native-library debugging.

At minimum, logs should eventually identify:

```text
configured runtime
configured device
compute type
worker count
runtime initialization success/failure
effective fallback if one occurs
```

Secrets or unnecessary machine-specific details should not be emitted.

## Deployment requirements

AMD/HIP deployment documentation must describe:

```text
supported/tested GPU architecture
TheRock runtime requirements
custom CTranslate2 build
OpenMP runtime requirement
required native DLLs
wheel packaging
runtime initialization order
validation commands
known unsupported combinations
```

The detailed investigation and build procedure should live outside the ADR and be referenced by it.

## Related decisions

- ADR-016 — Application Composition Root
- ADR-030 — Transcription Boundary and Faster-Whisper Adapter
- ADR-036 — Decouple Real-Time Audio Processing from Transcription Execution
- ADR-037 — Runtime Transcription Overload and Segment Rejection Policy
- ADR-039 — Multi-Source System and Microphone Audio Processing Architecture
- ADR-042 — Concurrent Transcription Execution with Multiple Whisper Workers

