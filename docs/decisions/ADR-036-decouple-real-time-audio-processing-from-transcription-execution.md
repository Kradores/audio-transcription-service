# ADR-036: Decouple Real-Time Audio Processing from Transcription Execution

## Status

Accepted

## Context

ADR-031 established the initial `SpeechPipeline` as a sequential processing
pipeline.

The pipeline processes captured audio through normalization, VAD, speech
segment assembly, and transcription. The synchronous `Transcriber` contract
is executed through `asyncio.to_thread()` so that model inference does not
block the asyncio event loop.

At the time of ADR-031, there was no measured evidence that a dedicated
transcription queue or concurrent execution model was required.

The first real end-to-end runtime test provided that evidence.

Faster-Whisper required approximately 3.1–3.3 seconds to transcribe a
5-second speech segment on the target runtime.

Because the speech pipeline waited for transcription to complete before
continuing to consume captured frames, the capture transport accumulated
backlog while transcription was executing.

With the original capture queue capacity, a real recording produced:

```text
frames_dropped=722
````

The resulting transcript contained missing phrases.

A controlled experiment increased the capture queue to 500 frames.

The capture callback produced approximately 441 samples at 44.1 kHz:

```text
441 / 44100 = 0.010 seconds
```

Therefore, the 500-frame queue provided approximately five seconds of audio
buffering.

With this configuration:

```text
frames_dropped=0
```

The same recording produced a complete and repeatable transcript across
multiple runs.

This demonstrates that the transcription stage was creating backpressure on
the real-time audio path.

Increasing the capture queue can absorb temporary backlog, but it does not
remove the architectural dependency between real-time audio processing and
transcription execution.

The system therefore requires an explicit boundary between these concerns.

## Decision

Real-time audio processing and transcription execution will be decoupled.

The real-time processing path will remain:

```text
AudioCapture
    ↓
AudioNormalizer
    ↓
AudioVad
    ↓
SpeechSegmentAssembler
    ↓
SpeechSegment
```

A completed `SpeechSegment` will then be submitted to a dedicated,
bounded transcription work queue.

A dedicated transcription worker will consume queued speech segments and
execute the existing synchronous `Transcriber` contract.

The resulting execution path is:

```text
AudioCapture
    ↓
AudioNormalizer
    ↓
AudioVad
    ↓
SpeechSegmentAssembler
    ↓
SpeechSegment
    ↓
bounded transcription queue
    ↓
single transcription worker
    ↓
Transcriber
    ↓
TranscriptionResult
    ↓
TranscriptionResultHandler
    ↓
TranscriptRecorder
```

### Single worker initially

The initial implementation will use exactly one transcription worker.

Multiple transcription workers are not introduced until runtime measurements
demonstrate that a single worker cannot provide sufficient throughput.

This avoids introducing unnecessary model concurrency, resource contention,
ordering complexity, and shutdown complexity before they are required.

### Transcriber contract remains synchronous

The existing application contract remains:

```python
transcribe(segment: SpeechSegment) -> TranscriptionResult
```

The transcription execution boundary owns scheduling and worker execution.

The concrete `Transcriber` implementation does not know whether it is being
called directly, from a worker thread, from a queue consumer, or through
another execution mechanism.

### Bounded transcription queue

The transcription work queue will be bounded.

An unbounded queue is rejected because sustained transcription backlog could
otherwise result in unbounded memory growth.

Queue capacity and overflow behavior are application-level execution concerns
and must be explicitly observable.

### Ordering

The initial single-worker implementation preserves chronological segment
ordering.

`TranscriptionResult` delivery remains in the same order as submitted
`SpeechSegment` objects.

Any future introduction of multiple workers must explicitly define ordering
semantics before implementation.

### Real-time path independence

The real-time audio-processing path must not wait for a transcription result.

A slow transcription operation may increase transcription latency or
transcription queue depth, but it must not directly block capture-frame
consumption.

The capture transport remains a bounded safety buffer for the real-time
capture boundary. It is not the intended buffer for normal transcription
inference latency.

### Persistence boundary

`TranscriptRecorder` remains downstream of completed
`TranscriptionResult` values.

This decision does not change the persistence boundary established by
ADR-033.

The transcription worker delivers completed results through the existing
result-delivery mechanism.

### Shutdown

The transcription worker is part of the pipeline/application lifecycle.

Shutdown must explicitly define how:

* queued transcription work is handled;
* an in-progress transcription is handled;
* the worker terminates;
* queued work is discarded or completed.

The implementation must not introduce ambiguous background work that survives
application shutdown.

The exact shutdown policy will be implemented and tested as part of this
decision.

## Consequences

### Positive

* Real-time audio processing is no longer directly blocked by Whisper
  inference.
* Capture-frame loss caused by sequential transcription backpressure is
  avoided under normal queue conditions.
* The capture queue no longer needs to absorb the full duration of
  transcription inference.
* Transcription execution becomes an independently observable subsystem.
* The synchronous `Transcriber` contract remains small and replaceable.
* A single worker provides deterministic transcription ordering.
* Future transcription concurrency can be introduced without redesigning the
  audio-processing components.

### Negative

* Transcription may temporarily lag behind real time.
* A second bounded queue introduces another lifecycle and failure boundary.
* Queue overflow behavior must be explicitly defined.
* Shutdown becomes more complex.
* The application must observe and diagnose transcription backlog.
* End-to-end latency may increase when transcription cannot keep up with
  incoming speech.

These trade-offs are preferable to losing captured audio.

## Alternatives Considered

### Increase the capture queue capacity

Rejected as the architectural solution.

A larger capture queue successfully prevented frame loss in the controlled
experiment, but it only converts transcription backpressure into additional
capture latency and queue memory usage.

The capture transport should not be responsible for buffering downstream ML
inference workload.

### Keep sequential transcription

Rejected.

Runtime measurement demonstrated that sequential transcription can fill the
capture queue and produce actual audio-frame loss.

### Use multiple transcription workers immediately

Rejected initially.

The current evidence establishes the need to decouple execution, but does not
yet establish the need for concurrent model inference.

Multiple workers would introduce additional CPU/memory consumption, model
contention, ordering, shutdown, and failure semantics.

A single worker is sufficient as the first execution model.

### Make `Transcriber` asynchronous

Rejected.

Scheduling and concurrency are application orchestration concerns.

Keeping `Transcriber` synchronous preserves the small replaceable contract
established by ADR-030.

### Use an unbounded transcription queue

Rejected.

An unbounded queue could cause unbounded memory growth if transcription
throughput falls below speech-segment production rate.

### Introduce an event bus or external message broker

Rejected.

The current application is a local service and has no demonstrated need for
distributed delivery, durability, or broker semantics.

A bounded in-process queue is sufficient for the current execution boundary.

## Observability

The transcription execution boundary should expose at least:

* queue capacity;
* queue depth;
* jobs submitted;
* jobs completed;
* jobs failed;
* queue wait duration;
* inference duration;
* transcription result delivery failures.

Capture observability remains responsible for:

* captured frame counts;
* dropped frame counts;
* capture recovery;
* capture lifecycle.

The two queues/boundaries must remain distinguishable in diagnostics.

## Testing Requirements

The implementation must provide tests covering:

* transcription work submission;
* single-worker execution;
* chronological result ordering;
* queue capacity;
* queue-full behavior;
* transcription failure;
* result-handler failure;
* worker startup and shutdown;
* queued work during shutdown;
* in-progress transcription during shutdown;
* continued audio-frame consumption while transcription is executing.

A real end-to-end runtime test must verify that the decoupled architecture does
not reproduce the previously observed capture-frame loss under the same
workload.

The existing Faster-Whisper integration tests remain responsible for verifying
the concrete transcription adapter.

## Related Decisions

* ADR-005 — Architectural Boundaries
* ADR-016 — Application Composition Root
* ADR-018 — Audio Capture Architecture
* ADR-026 — Audio Frame Transport Threading and Asynchronous Consumption
* ADR-030 — Transcription Boundary and Faster-Whisper Adapter
* ADR-031 — Speech Pipeline Orchestration and Transcription Scheduling
* ADR-032 — Transcription Result Delivery Contract
* ADR-033 — Transcription Result Persistence Boundary
* ADR-035 — Audio Capture Discontinuity Propagation and Processing State Reset

