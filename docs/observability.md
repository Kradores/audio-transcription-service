# Observability

## Purpose

Observability is intentionally diagnostic rather than a full telemetry
platform.

The service must make it possible to distinguish failures and pressure at
different runtime boundaries without logging every 20 ms audio frame.

The current runtime architecture is:

```text
System AudioCapture ─┐
                     │
                     ▼
              SpeechPipeline
                     │
                     │ source-tagged work
                     ▼
              TranscriptionExecutor
                     │
                     ▼
              Faster-Whisper
                     │
                     ▼
             TranscriptRecorder
                     │
                     ▼
                   SQLite

Microphone AudioCapture
          │
          ▼
   SpeechPipeline
          │
          └──────────────► shared TranscriptionExecutor
```

The primary diagnostic questions are:

1. Is real-time audio capture healthy?
2. Is speech segmentation producing reasonable work units?
3. Is transcription keeping up with those work units?
4. If not, where is latency or loss occurring?
5. Is overload affecting one source more than the other?

## Logging strategy

The application uses the standard-library `logging` package as defined by
ADR-017.

Logs are emitted for lifecycle events, semantic audio events, recovery,
backpressure, transcription execution, and persistence.

The service deliberately avoids per-frame logging during normal operation.

Transcript text is not logged at INFO level.

Transcript text may be logged at DEBUG level for controlled diagnostic runs.

---

## Audio capture

Each capture path owns its own native session and bounded frame transport.

Important capture events include:

- capture started;
- selected native device;
- native sample rate and channel count;
- native capture-frame format;
- Windows device monitor started and stopped;
- matching Windows default-device changes;
- capture recovery started;
- capture recovery attempt failed;
- capture recovered;
- stream becoming inactive;
- capture discontinuity;
- capture stopped;
- total dropped capture frames.

Capture-frame drops indicate pressure at the real-time capture boundary.

They must not be confused with transcription-segment rejection.

A healthy capture shutdown should include:

```text
audio capture stopped frames_dropped=0
```

A non-zero value means the real-time audio path was unable to consume native
capture frames quickly enough.

---

## Capture recovery

System-audio and microphone recovery are independent.

System-audio recovery follows:

```text
eRender / eConsole change
        ↓
capture device-change signal
        ↓
settle/debounce period
        ↓
capture recovery
        ↓
fresh PyAudio session
        ↓
current default loopback selected
        ↓
capture recovered
```

Microphone recovery follows the equivalent:

```text
eCapture / eConsole change
        ↓
capture device-change signal
        ↓
settle/debounce period
        ↓
capture recovery
        ↓
fresh PyAudio session
        ↓
current default input selected
        ↓
capture recovered
```

A recovery triggers a discontinuity only for the affected source.

`SpeechPipeline` resets:

```text
AudioNormalizer
AudioVad
SpeechSegmentAssembler
```

before processing recovered audio.

A short audio gap during a real Windows device transition is expected.

Windows may temporarily expose no usable endpoint while devices disappear,
appear, or change profile.

The recovery guarantee is therefore not gapless audio.

The guarantee is:

> Once Windows exposes a usable selected default endpoint, capture recovers
> automatically without restarting the application.

---

## Speech pipeline

There is one `SpeechPipeline` per source:

```text
system_audio
microphone
```

Pipeline logs include `source=` so events from the two real-time paths can be
distinguished.

Important events include:

- pipeline started;
- `SpeechStart`;
- `SpeechEnd`;
- capture discontinuity / processing-state reset;
- speech segment emitted;
- segment rejected by the transcription executor;
- processing failure;
- pipeline stopped.

### Pipeline statistics

Each pipeline tracks:

- `captured_frames`
  - frames consumed from `AudioCapture`;

- `processing_frames`
  - normalized 20 ms processing frames produced;

- `segments_emitted`
  - complete speech segments produced by the assembler;

- `segments_rejected`
  - emitted segments rejected by the shared transcription executor;

- `short_segments`
  - emitted segments shorter than 1 second;

- `segment_seconds_average`
  - average duration of all emitted segments;

- `segment_seconds_max`
  - maximum emitted segment duration.

Segment-duration statistics describe the output of the assembler.

They are calculated before transcription submission, so rejected work remains
represented in segmentation statistics.

This is important because the purpose of these metrics is to answer whether
the producer is creating too many small transcription jobs.

A typical shutdown summary is:

```text
speech pipeline stopped
source=microphone
captured_frames=...
processing_frames=...
segments_emitted=...
segments_rejected=...
short_segments=...
avg_segment_duration=...
max_segment_duration=...
```

The system-audio pipeline emits the equivalent summary with:

```text
source=system_audio
```

---

## Transcription executor

Both source pipelines share one bounded `TranscriptionExecutor`.

The executor is the boundary between real-time audio processing and
resource-sensitive transcription.

The executor tracks:

- `submitted`
  - work items successfully accepted by the bounded queue;

- `completed`
  - accepted work successfully transcribed and delivered to the result handler;

- `rejected`
  - submissions rejected because executor capacity was exhausted;

- `failed`
  - accepted work that failed during transcription or result delivery;

- `queue_depth`
  - current number of queued work items;

- `queue_high_water_mark`
  - maximum queue depth observed during the runtime;

- `queue_wait_seconds_average`
  - average time accepted work waited before transcription began;

- `queue_wait_seconds_max`
  - maximum observed queue wait;

- `transcription_seconds_average`
  - average executor service time for processed work;

- `transcription_seconds_max`
  - maximum executor service time observed.

### Submission semantics

`submitted` means:

> The work item was accepted into the bounded transcription executor.

Rejected work is counted separately.

After a graceful shutdown where all accepted work is drained, the useful
invariant is:

```text
submitted = completed + failed
```

`rejected` is outside that equation because rejected segments never entered
the executor workload.

### Queue high-water mark

If:

```text
queue_high_water_mark < queue_capacity
```

the executor never reached its configured capacity during the run.

If:

```text
queue_high_water_mark == queue_capacity
```

the queue became fully saturated at least once.

This does not by itself mean work was lost.

Actual overload loss is represented by:

```text
rejected > 0
```

### Queue wait

Queue wait measures the delay between:

```text
segment accepted
        ↓
wait in bounded executor queue
        ↓
worker begins transcription
```

Increasing queue wait indicates that transcription work is arriving faster
than the worker can service it.

This is one of the primary metrics for deciding whether the current
single-worker execution model has enough capacity.

### Transcription duration

Transcription duration measures the executor service time for one work item.

This is distinct from queue wait.

Conceptually:

```text
total executor latency for one accepted item
        =
queue wait
        +
transcription/result-delivery service
```

The Faster-Whisper adapter also logs per-call inference timing.

The executor aggregates timings across the complete runtime so long-running
behavior can be evaluated without manually parsing every inference log.

### Overload

When the queue cannot accept more work:

```text
transcription executor overloaded
source=...
queue_capacity=...
queue_depth=...
queue_high_water_mark=...
rejected=...
```

The submission returns `False`.

The corresponding `SpeechPipeline` increments:

```text
segments_rejected
```

and continues processing real-time audio.

This behavior is defined by ADR-037.

The service prioritizes keeping the real-time audio path alive over
guaranteeing transcription completeness during sustained overload.

### Executor shutdown summary

A graceful shutdown emits a summary similar to:

```text
transcription executor stopped
submitted=...
completed=...
rejected=...
failed=...
queue_high_water_mark=...
avg_queue_wait=...
max_queue_wait=...
avg_transcription_duration=...
max_transcription_duration=...
```

This is the primary summary for transcription-capacity investigations.

---

## Faster-Whisper

The Faster-Whisper adapter logs:

```text
transcription started
```

with:

- source segment start;
- source segment duration.

It then logs:

```text
transcription inference completed
```

with:

- segment start;
- segment duration;
- inference duration;
- detected language.

These logs are useful for investigating individual unusually slow or
incorrect transcriptions.

Long-running throughput analysis should primarily use the aggregate
`TranscriptionExecutor` statistics.

---

## Transcript recorder

The recorder logs:

- successful persistence;
- persistence failures;
- source;
- transcript start and end timestamps.

Successful recorder completion means the repository operation completed
successfully.

SQLite-specific SQL logging is not required during normal operation.

---

## Backpressure interpretation

The service has two different bounded pressure boundaries.

### Capture pressure

```text
native audio callback
        ↓
capture transport
        ↓
SpeechPipeline
```

Evidence:

```text
frames_dropped > 0
```

This means the real-time audio path could not consume capture frames quickly
enough.

### Transcription pressure

```text
SpeechSegment
        ↓
TranscriptionExecutor queue
        ↓
Whisper worker
```

Evidence includes:

```text
queue_high_water_mark
queue wait
rejected
```

These failure modes must not be conflated.

The architecture is specifically designed so that transcription overload does
not directly block capture processing.

---

## Throughput investigation

The current observability milestone exists to support the next performance
decision:

```text
segment aggregation
vs.
additional transcription worker capacity
vs.
a combination
```

The decision must be based on runtime evidence rather than assumption.

### Evidence suggesting segmentation pressure

Examples:

```text
large segments_emitted count
high short_segments count
low avg_segment_duration
```

This suggests the pipeline is producing many small Whisper jobs.

In that case, segment aggregation or segmentation tuning may reduce fixed
per-transcription overhead.

### Evidence suggesting execution-capacity pressure

Examples:

```text
reasonable segment durations
queue_high_water_mark == queue_capacity
large queue waits
rejected > 0
```

This suggests the worker cannot service the incoming workload quickly enough.

Additional execution capacity may need evaluation.

### Evidence suggesting machine/resource contention

Examples:

```text
transcription duration varies heavily
max_transcription_duration much larger than average
performance degrades while other applications are busy
```

This suggests model execution itself is sensitive to current machine load.

Adding workers could make this better or worse and must therefore be
benchmarked rather than assumed to improve throughput.

### Likely combination

If runtime evidence shows both:

```text
many short segments
and
sustained executor backlog
```

then the eventual solution may combine:

```text
fewer / better-sized work items
+
additional execution capacity where hardware supports it
```

No throughput strategy has been selected yet.

---

## Realistic runtime validation

Short integration tests are not sufficient to evaluate transcription
throughput.

For throughput investigations, run a realistic two-sided conversation for at
least 10–30 minutes.

Record:

```text
system SpeechPipeline shutdown summary
microphone SpeechPipeline shutdown summary
TranscriptionExecutor shutdown summary
```

Also record the runtime configuration:

```text
Whisper model
device
compute_type
transcription queue capacity
segmentation settings
```

For comparison between runs, avoid changing multiple performance-sensitive
parameters at once.

The next throughput decision should be made only after collecting these
measurements.

---

## Deliberately not implemented

The current observability implementation does not introduce:

- Prometheus;
- OpenTelemetry;
- external metrics storage;
- a custom metrics framework;
- per-frame logs;
- percentile/histogram infrastructure;
- CPU/GPU telemetry;
- adaptive executor behavior;
- automatic queue resizing.

These may be introduced later when a concrete requirement justifies them.


## Transcription aggregation

Each source pipeline reports semantic segmentation and transcription
aggregation separately.

Semantic segment statistics:

- `segments_emitted`
- `short_segments`
- `avg_segment_duration`
- `max_segment_duration`

Aggregation statistics:

- `aggregation_received`
- `aggregation_emitted`
- `aggregation_combined`
- `avg_aggregate_duration`
- `max_aggregate_duration`

`segments_emitted` describes completed semantic segments produced by
`SpeechSegmentAssembler`.

`aggregation_emitted` describes the actual `SpeechSegment` work units emitted
by `TranscriptionSegmentAggregator` toward `TranscriptionExecutor`.

`segments_rejected` counts transcription segments rejected by the shared
executor after aggregation.

This allows runtime diagnosis across:

semantic segmentation
→ aggregation
→ executor submission
→ queue pressure
→ transcription