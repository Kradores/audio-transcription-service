# ADR-042: Concurrent Transcription Execution with Multiple Whisper Workers

## Status

Accepted

## Date

2026-08-25

## Context

ADR-036 separated resource-sensitive transcription execution from the real-time audio path through a bounded `TranscriptionExecutor`.

ADR-037 established that transcription overload is a normal runtime condition and that:

```text
submit()
    ↓
accepted → bounded queue
rejected → drop newest work
```

must remain non-blocking.

ADR-039 introduced two independent source-processing paths:

```text
system_audio
microphone
```

which converge on one shared transcription executor.

ADR-041 subsequently introduced per-source transcription-segment aggregation to reduce inefficient Whisper invocations before they reach the shared executor.

The current execution topology is therefore:

```text
system aggregator ───────┐
                         │
                         ▼
                 bounded shared queue
                         │
                         ▼
                  one executor worker
                         │
                         ▼
                    one Transcriber
                         │
                         ▼
                    Faster-Whisper

microphone aggregator ───┘
```

The current executor deliberately uses one worker. The existing implementation owns a single `Transcriber`, one bounded FIFO queue, and one worker task. 

This single-worker design was intentional. ADR-036 explicitly deferred multiple workers until runtime measurement demonstrated that they were required.

That evidence now exists.

### Pre-aggregation natural conversation

A realistic dual-source conversation previously produced:

```text
semantic/transcription jobs = 414
accepted                   = 308
rejected                   = 106
rejection rate             ≈ 25.6%

average queue wait         ≈ 32.9 s
p90 queue wait             ≈ 53.1 s
maximum queue wait         ≈ 75.7 s
```

The executor repeatedly reached its configured queue capacity.

### Aggregation experiment

ADR-041 addressed the substantial number of very small Whisper requests before increasing execution capacity.

The subsequent natural-conversation test produced approximately:

```text
semantic segments          = 583
transcription jobs         = 479
accepted                   = 377
rejected                   = 102

aggregation reduction      ≈ 17.8%
executor rejection rate    ≈ 21.3%
```

The workload was more fragmented than the earlier test, yet aggregation reduced the number of Whisper invocations and reduced executor rejection percentage.

However, the shared queue still repeatedly reached:

```text
queue_depth = 10
queue_high_water_mark = 10
```

and overload persisted throughout the conversation.

The observed inference time also remained variable. Individual transcription requests sometimes took substantially longer than their audio duration.

Therefore the runtime evidence now distinguishes two separate issues:

```text
inefficient job formation
        ↓
ADR-041 improved this

insufficient execution capacity
        ↓
still present
```

Increasing execution concurrency is now justified independently of speech-segment aggregation.

---

# Decision

## 1. `TranscriptionExecutor` will support multiple concurrent workers

The shared executor will support a configuration-driven number of transcription workers.

Conceptually:

```text
                       bounded queue
                            │
            ┌───────────────┼───────────────┐
            ▼               ▼               ▼
         worker 1         worker 2       worker N
            │               │               │
            ▼               ▼               ▼
       Transcriber     Transcriber      Transcriber
```

The initial benchmark configuration will use:

```yaml
transcription:
  worker_count: 2
```

`worker_count = 1` remains supported and retains the current single-worker behavior.

The worker count is configuration, not an architectural constant.

---

## 2. One shared transcription queue remains authoritative

Multiple workers will consume from **one shared bounded FIFO queue**.

The architecture does not introduce:

```text
system queue
microphone queue
```

or:

```text
one queue per worker
```

The topology remains:

```text
system_audio ─┐
              │
              ▼
       shared bounded queue
              │
       ┌──────┴──────┐
       ▼             ▼
    worker 1      worker 2
       ▲             ▲
       │             │
microphone ──────────┘
```

This preserves:

- one overload boundary;
- one configured queue capacity;
- shared resource control;
- simple FIFO dispatch;
- existing source-independent executor semantics.

Per-source fairness or prioritization remains outside this decision.

---

## 3. Queue submission behavior remains unchanged

The executor contract remains:

```python
submit(item: TranscriptionWorkItem) -> bool
```

Submission remains synchronous and non-blocking.

The semantics defined by ADR-037 remain:

```text
True
    accepted

False
    executor capacity exhausted
```

Rejected work is not retried.

No secondary queue is introduced.

No blocking producer behavior is introduced.

Multiple workers increase service capacity; they do not weaken the bounded-overload guarantee.

---

## 4. Queue capacity and active execution are distinct

With one worker, the current mental model is approximately:

```text
1 active transcription
+
up to queue_capacity waiting
```

With `N` workers it becomes:

```text
up to N active transcriptions
+
up to queue_capacity waiting
```

Therefore the maximum accepted-but-not-completed workload becomes approximately:

```text
worker_count + queue_capacity
```

For the initial configuration:

```text
worker_count   = 2
queue_capacity = 10

maximum accepted in-flight work
≈ 12
```

`queue_capacity` continues to mean the bounded waiting queue, not total active-plus-waiting work.

This distinction must be explicit in observability documentation.

---

## 5. Each executor worker owns one `Transcriber` dependency

The generic executor will not concurrently invoke the same `Transcriber` object from multiple workers.

Instead:

```text
worker 1 → transcriber 1
worker 2 → transcriber 2
...
worker N → transcriber N
```

Conceptually, executor construction becomes:

```text
TranscriptionExecutor
    ├── Transcriber 1
    ├── Transcriber 2
    └── ...
```

This is deliberate.

The application-level `Transcriber` contract currently says:

```text
SpeechSegment → TranscriptionResult
```

It does not establish thread-safety or concurrent-invocation semantics.

Requiring every future `Transcriber` implementation to support concurrent calls on one instance would unnecessarily strengthen that contract.

Worker-local transcriber ownership preserves replaceability.

---

## 6. The initial Faster-Whisper implementation will share one `WhisperModel`

Although executor workers own distinct `FasterWhisperTranscriber` objects, those adapter objects will initially reference one shared Faster-Whisper `WhisperModel`.

Conceptually:

```text
worker 1
    ↓
FasterWhisperTranscriber 1
              │
              ├────────────┐
              │            │
worker 2      │            ▼
    ↓         │     shared WhisperModel
FasterWhisperTranscriber 2 │
              │            │
              └────────────┘
```

The shared model will be created with model concurrency corresponding to the configured executor worker count.

For the initial two-worker experiment:

```text
executor workers = 2
Faster-Whisper num_workers = 2
```

Faster-Whisper passes this worker configuration to CTranslate2's `inter_threads`, which is specifically intended to allow multiple requests to execute in parallel. CTranslate2 also documents concurrent Python-thread execution as a supported parallelization mode. 

This is preferred initially over independently loading:

```text
WhisperModel #1
WhisperModel #2
```

because separate top-level model instances would duplicate model lifecycle and potentially increase memory consumption unnecessarily.

The concrete Faster-Whisper model-sharing strategy remains encapsulated in composition and the transcription adapter. The generic executor does not depend on Faster-Whisper or CTranslate2 concepts.

---

## 7. Executor concurrency and model concurrency must match

Creating multiple executor workers without corresponding model execution capacity is not considered a valid Faster-Whisper configuration for this architecture.

For example:

```text
executor workers = 2
Whisper model workers = 1
```

could result in:

```text
two application tasks
        ↓
one model execution slot
        ↓
serialized inference
```

which would add orchestration complexity without providing the intended throughput increase.

The composition root is responsible for constructing compatible dependencies.

The application configuration should therefore expose **one application-level execution setting**:

```yaml
transcription:
  worker_count: 2
```

rather than independent user-facing values such as:

```yaml
transcription:
  worker_count: 2

whisper:
  num_workers: 2
```

Two independent settings could enter contradictory states.

For Faster-Whisper, composition maps:

```text
transcription.worker_count
        ↓
executor worker count
        +
WhisperModel num_workers
```

This keeps one source of truth for application concurrency.

---

## 8. Work dispatch is FIFO; result completion order is not guaranteed

The shared queue remains FIFO.

Therefore workers claim accepted work in queue order.

With concurrent execution, however:

```text
job A starts first
job B starts second

job B may finish first
```

Consequently, the executor no longer guarantees result-delivery order when:

```text
worker_count > 1
```

This is acceptable.

ADR-039 already established:

```text
database insertion order ≠ conversation order
```

and defined timestamps plus source identity as the authoritative conversation ordering mechanism.

Therefore persistence order may become:

```text
segment B
segment A
```

even when:

```text
A.start < B.start
```

Consumers reconstructing conversation order must use:

```text
start_time
source
```

rather than SQLite `id`.

No executor-side reordering buffer will be introduced.

---

## 9. Result delivery remains synchronous on the application event loop

Each executor worker will continue to perform expensive synchronous transcription outside the asyncio event loop.

Conceptually:

```text
worker task
    ↓
asyncio.to_thread(...)
    ↓
Transcriber.transcribe()
    ↓
return result to event loop
    ↓
on_result(...)
```

The synchronous result handler remains outside the model worker thread.

This preserves the existing SQLite ownership behavior and avoids introducing concurrent access to the current SQLite connection solely because inference became concurrent.

If result delivery itself later becomes a measurable bottleneck, that will be addressed separately.

---

## 10. One failed transcription does not stop other workers

Existing failure isolation remains.

For one accepted item:

```text
worker
    ↓
transcribe
    ↓
exception
    ↓
failed += 1
    ↓
log
    ↓
same worker continues
```

Other workers continue independently.

A failure processing one work item does not:

- terminate the executor;
- cancel sibling workers;
- retry the failed item;
- affect real-time capture.

The graceful-shutdown invariant remains:

```text
submitted = completed + failed
```

after all accepted work has drained.

---

## 11. Unexpected worker lifecycle failure must be observable

Per-item transcription failures are expected to be isolated.

An executor worker itself terminating unexpectedly is different.

The executor must not silently degrade from:

```text
2 workers
```

to:

```text
1 worker
```

while continuing indefinitely without diagnostics.

Unexpected worker termination must therefore be observable and surfaced through executor lifecycle/error handling.

Automatic worker restart is not introduced by this decision.

If later evidence demonstrates that worker restart is necessary, recovery semantics should be designed explicitly.

---

## 12. Graceful shutdown drains all accepted work

The existing higher-level lifecycle remains:

```text
stop system source
        ↓
flush system aggregator

stop microphone source
        ↓
flush microphone aggregator

no new source work
        ↓
stop executor
```

ADR-039 already ensures the source pipelines stop before the shared executor. 

With multiple workers, executor shutdown becomes conceptually:

```text
accepting = false
        ↓
all already-accepted queue work continues
        ↓
workers consume remaining jobs concurrently
        ↓
all accepted jobs complete or fail
        ↓
all worker loops terminate
        ↓
executor stop completes
```

Shutdown must wait for **all** workers.

No accepted work may be abandoned merely because another worker has already become idle.

The executor must remain idempotent and retain existing stop-before-start behavior.

---

## 13. Shutdown signaling is per worker

A single shutdown sentinel is sufficient for one worker but is insufficient when several workers independently consume the queue.

The multi-worker implementation must guarantee that every worker receives a termination condition.

The exact implementation may use:

- one sentinel per worker; or
- queue draining followed by explicit worker cancellation/termination.

This is an implementation detail.

The architectural requirement is:

> every accepted work item is drained before every worker terminates.

No worker may consume a shutdown signal that allows accepted work behind it to be abandoned.

---

## 14. Existing executor statistics remain aggregate executor statistics

The current statistics remain meaningful:

```text
submitted
completed
rejected
failed

queue_depth
queue_high_water_mark

avg_queue_wait
max_queue_wait

avg_transcription_duration
max_transcription_duration
```

They continue to describe the complete shared executor rather than individual workers. 

The following concurrency diagnostics will be added:

```text
worker_count
active_workers
active_workers_high_water_mark
```

The shutdown summary should include at minimum:

```text
worker_count=2
max_active_workers=2
```

This allows us to distinguish:

```text
two workers configured
```

from:

```text
two workers actually executing simultaneously
```

Per-worker lifetime totals are not required initially.

---

## 15. Worker identity should be present in execution logs

Individual execution logs should allow concurrent jobs to be distinguished.

For example:

```text
transcription worker started worker_id=1
transcription worker started worker_id=2
```

and executor completion/failure diagnostics may include:

```text
worker_id=...
source=...
start=...
end=...
```

Worker identity is diagnostic execution metadata.

It does not become part of:

- `SpeechSegment`;
- `TranscriptionResult`;
- persistence;
- conversation reconstruction.

---

## 16. CPU resource contention must be measured

The current deployment uses:

```text
Whisper small
CPU
int8
```

CTranslate2 distinguishes:

```text
inter_threads
```

for concurrent model workers and:

```text
intra_threads
```

for computation threads used by each worker.

Its performance guidance explicitly warns against allowing:

```text
inter_threads × intra_threads
```

to exceed available physical CPU cores and recommends favoring additional inter-thread parallelism for large workloads. 

Therefore:

```text
2 workers
```

does **not** imply:

```text
2× throughput
```

on every machine.

More concurrency may cause:

- CPU oversubscription;
- memory pressure;
- cache contention;
- thermal throttling;
- longer individual inference duration.

Worker count must remain configuration-driven and empirically benchmarked.

The architecture does not auto-detect or auto-scale worker count initially.

---

## 17. Initial worker count is two

The first concurrent configuration will be:

```yaml
transcription:
  queue_capacity: 10
  worker_count: 2

  aggregation:
    enabled: true
    target_duration_seconds: 5.0
    max_duration_seconds: 10.0
    max_gap_seconds: 1.5
    max_wait_seconds: 2.0
```

Two is chosen because it is the smallest concurrency increase capable of testing the hypothesis.

We will not jump directly to:

```text
3
4
CPU-count-derived
```

workers.

This isolates the experiment and limits resource risk.

---

## 18. Aggregation settings remain unchanged during the concurrency benchmark

ADR-041 settings will remain unchanged during the first multi-worker test.

We will not simultaneously tune:

- aggregation target;
- aggregation max wait;
- queue capacity;
- VAD;
- segmentation;
- model size;
- language policy.

The comparison must isolate:

```text
worker_count = 1
```

versus:

```text
worker_count = 2
```

This follows the project's measure-before-optimization principle.

---

# Resulting architecture

```text
                 system_audio pipeline
                         │
                  semantic segments
                         │
                    aggregator
                         │
                         ├─────────────┐
                                       │
                                       ▼
                           shared bounded FIFO queue
                                       │
                           ┌───────────┴───────────┐
                           │                       │
                           ▼                       ▼
                       worker 1                worker 2
                           │                       │
                    Transcriber 1            Transcriber 2
                           │                       │
                           └───────────┬───────────┘
                                       │
                                 shared model
                                num_workers=2
                                       │
                                  Faster-Whisper
                                       │
                              TranscriptionResult
                                       │
                                  result handler
                                       │
                                    SQLite
                                       ▲
                                       │
                         ┌─────────────┘
                         │
                    aggregator
                         │
                  semantic segments
                         │
                microphone pipeline
```

---

# Consequences

### Positive

**Higher possible transcription throughput.** Two jobs may execute concurrently instead of waiting for one serial service slot.

**Lower queue pressure.** If the machine has sufficient compute capacity, queue wait and rejection should decrease.

**Existing real-time guarantees remain.** Capture and speech processing remain independent of model inference.

**Bounded memory behavior remains.** The shared waiting queue remains fixed-size.

**No new source-specific scheduling.** Both sources still use one shared executor.

**Transcriber abstraction remains replaceable.** Each generic executor worker owns one `Transcriber`; concurrent safety is not imposed on a single application-level instance.

**Conversation reconstruction remains valid.** ADR-039 already uses timestamps rather than insertion order.

### Negative

**Result completion order becomes nondeterministic.**

**Resource usage increases.** Multiple CTranslate2 workers consume additional memory and CPU/GPU resources.

**Individual inference may become slower.** Contention may increase service time despite improved total throughput.

**Executor lifecycle becomes more complex.** Several worker tasks must start, drain, fail, and terminate correctly.

**Observability becomes more complex.** Configured concurrency and actual active concurrency must be distinguishable.

---

# Alternatives considered

### Keep one worker and increase queue capacity

Rejected as the primary solution.

A larger queue increases tolerated latency but does not increase service throughput.

The natural-call tests already demonstrate sustained overload, not merely a short transient burst.

### Further tune aggregation before concurrency

Deferred.

ADR-041 already produces a measurable reduction in Whisper invocation count.

The executor still saturates after that optimization.

Further aggregation tuning may eventually be useful, but it should not obscure the now-demonstrated execution-capacity constraint.

### Create multiple executor workers using the current model configuration unchanged

Rejected.

Multiple application tasks do not guarantee parallel model execution if the underlying Faster-Whisper/CTranslate2 model has only one execution worker.

Executor and model concurrency must be intentionally aligned.

### Load one independent Whisper model per executor worker

Not selected initially.

This would provide obvious model isolation but duplicates model lifecycle and likely consumes substantially more memory.

Faster-Whisper/CTranslate2 already provides native support for multiple concurrent execution workers on one model object. 

Separate top-level models remain a fallback if real testing demonstrates that shared-model concurrent execution is unstable or underperforms.

### Share one application `Transcriber` instance across all executor workers

Rejected as the generic executor contract.

Even though the current `FasterWhisperTranscriber` is effectively stateless around its model call, the application-owned `Transcriber` protocol does not currently guarantee thread safety.

Worker-local transcriber instances preserve a weaker and more replaceable contract.

### One executor per audio source

Rejected.

This would fragment global resource control and potentially allow each source to independently consume full model capacity.

ADR-039 deliberately established one shared transcription execution boundary.

### Preserve completion order through an output reorder buffer

Rejected.

ADR-039 already establishes timestamp-based conversation ordering.

A reorder buffer would add latency and state solely to recreate an insertion-order property that is not authoritative.

### Automatically select worker count from CPU core count

Rejected initially.

Hardware characteristics alone do not determine optimal Faster-Whisper concurrency.

Model size, compute type, competing applications, thermal behavior, and memory availability all matter.

The worker count remains explicit configuration.

---

# Testing requirements

Before real-call validation, the implementation should prove:

- `worker_count=1` preserves current behavior;
- two workers can actually process two blocking fake transcriptions concurrently;
- the shared queue remains FIFO for work acquisition;
- completion may occur out of submission order;
- all accepted work is completed or failed during graceful shutdown;
- every worker terminates;
- stop remains idempotent;
- stop-before-start remains harmless;
- queue-full rejection remains non-blocking;
- one work-item failure does not stop sibling workers;
- one work-item failure does not kill its own worker;
- result-handler failure remains counted as failed;
- `active_workers` returns to zero;
- `active_workers_high_water_mark` reaches two in the concurrency test;
- source identity is preserved regardless of which worker handles a job;
- aggregate statistics satisfy:

```text
submitted = completed + failed
```

after graceful shutdown.

Composition tests should additionally prove that configured:

```text
worker_count=N
```

creates:

```text
N executor worker transcribers
```

and configures the initial Faster-Whisper model for corresponding concurrent execution.

---

# Benchmark acceptance criteria

I would **not** define success as “two workers are faster.”

The two-worker configuration should only become the new default if the realistic call benchmark shows a worthwhile system-level improvement.

Compare:

```text
A: aggregation + 1 worker
B: aggregation + 2 workers
```

using:

- `frames_dropped` per source;
- semantic segments;
- aggregation received/emitted/combined;
- executor submitted;
- executor completed;
- executor rejected;
- rejection rate;
- queue high-water mark;
- average queue wait;
- maximum queue wait;
- average transcription duration;
- maximum transcription duration;
- maximum active workers;
- total graceful shutdown drain time;
- approximate process CPU and memory behavior;
- persisted result count.

The primary goal is:

```text
substantially fewer rejected transcripts
+
substantially lower queue wait
+
frames_dropped remains 0
```

without unacceptable resource contention.

A useful outcome could even be:

```text
per-job inference becomes somewhat slower
```

while:

```text
global throughput improves enough
to reduce queue wait and rejection substantially
```

because system throughput—not individual call latency—is the capacity problem we're solving.

If two workers produce little or no throughput gain while greatly increasing CPU/RAM pressure, we revert to one worker and investigate model/thread configuration rather than adding more workers.

---

# Related decisions

- ADR-030 — Transcription Boundary and Faster-Whisper Adapter
- ADR-031 — Speech Pipeline Orchestration and Transcription Scheduling
- ADR-036 — Decouple Real-Time Audio Processing from Transcription Execution
- ADR-037 — Runtime Transcription Overload and Segment Rejection Policy
- ADR-039 — Multi-Source System and Microphone Audio Processing Architecture
- ADR-041 — Per-Source Speech Segment Aggregation Before Transcription Execution
