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

Normal logging is emitted both to console and, when configured, to a bounded rotating file.

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
an executor worker begins transcription
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
worker_count=...
max_active_workers=...
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

### Worker concurrency

The executor also reports:

- `worker_count`
  - configured number of executor workers;

- `active_workers`
  - number of workers currently executing transcription;

- `active_workers_high_water_mark`
  - maximum number of transcription operations observed concurrently.

Configured concurrency and observed concurrency are intentionally separate.

For example:

```text
worker_count=2
max_active_workers=2
```
confirms that two configured workers actually executed transcription
concurrently during the run.

A value such as:
```
worker_count=2
max_active_workers=1
```
means two workers were configured but no overlapping transcription execution
was observed.

Individual executor-worker logs include:

```text
transcription worker started worker_id=...
transcription completed worker_id=... source=... start=... end=...
transcription execution failed worker_id=... source=... start=... end=...
transcription worker stopped worker_id=...
```

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


## Transcription concurrency

The shared transcription executor may run multiple concurrent workers.

Concurrency diagnostics include:

- `worker_count`
  - configured number of transcription executor workers;

- `active_workers`
  - number of workers currently executing transcription;

- `active_workers_high_water_mark`
  - maximum number of transcription operations observed concurrently.

Configured concurrency and observed concurrency are intentionally separate.

For example:

```text
worker_count=2
max_active_workers=2
```

confirms that both configured workers actually executed transcription
concurrently.

By contrast:

```text
worker_count=2
max_active_workers=1
```

means two workers were configured but the workload did not produce overlapping
transcription execution during that run.

Worker lifecycle and execution logs include diagnostic worker identity:

```text
transcription worker started worker_id=...
transcription completed worker_id=... source=... start=... end=...
transcription execution failed worker_id=... source=... start=... end=...
transcription worker stopped worker_id=...
```

`worker_id` is execution metadata only.

It is not persisted and must not be used for conversation ordering.

### Interpreting transcription capacity

Worker count must not be evaluated from one metric alone.

The important signals are:

```text
worker_count
max_active_workers

submitted
completed
rejected
failed

queue_high_water_mark
avg_queue_wait
max_queue_wait

avg_transcription_duration
max_transcription_duration

frames_dropped
```

A queue high-water mark equal to queue capacity means the executor experienced
a period of maximum waiting pressure.

It does not by itself mean the service was unhealthy.

For example:

```text
queue_high_water_mark=10
rejected=0
```

means the waiting queue became full temporarily but workers drained it before
new work needed to be rejected.

Sustained executor pressure is better indicated by a combination such as:

```text
queue_high_water_mark == queue_capacity
+
high average queue wait
+
non-zero rejected
```

Capture pressure and transcription pressure remain different conditions.

```text
frames_dropped > 0
```

means the real-time capture/processing path could not keep up.

```text
rejected > 0
```

means the bounded transcription executor could not accept all generated
transcription work.

A healthy real-time path may therefore legitimately report:

```text
frames_dropped=0
rejected>0
```

during CPU-intensive transcription overload.

### Worker-count benchmark reference

Real-conversation validation of ADR-042 produced the following approximate
operating points on the benchmark machine:

| Workers | Rejection | Avg queue wait | Avg inference |
| ---: | ---: | ---: | ---: |
| 1 | 18.36% | 28.263 s | 4.207 s |
| 2 | 9.52% | 17.676 s | 6.740 s |
| 3 | 0% | 10.779 s | 8.130 s |

All measured runs retained:

```text
frames_dropped=0
failed=0
```

The three-worker run kept CPU utilization above approximately 90% during
intensive conversation.

The operational interpretation is:

```text
1 worker
    lower resource use
    but insufficient throughput for measured intensive conversations

2 workers
    selected default
    balanced throughput and resource pressure

3 workers
    higher measured throughput
    but high sustained CPU pressure
```

These numbers are benchmark-machine observations, not universal performance
targets.

Hardware, competing applications, model configuration, and conversation
intensity can materially change them.

For this reason `worker_count` remains explicit configuration rather than an
automatically scaled value.

### Graceful shutdown diagnostics

A healthy multi-worker shutdown must drain all accepted work before workers
terminate.

The final executor accounting must satisfy:

```text
submitted = completed + failed
```

The expected ordering is:

```text
source pipelines stop
        ↓
pending aggregates flush
        ↓
accepted executor work drains
        ↓
final transcription completes
        ↓
result is delivered/persisted
        ↓
transcription workers stop
        ↓
executor shutdown summary
```

An inference completion appearing after:

```text
transcription worker stopped
```

is a lifecycle defect and must be investigated.

The executor shutdown summary should expose at least:

```text
worker_count=...
max_active_workers=...
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


## Windows capture and PortAudio refresh

Default-device recovery must be observable separately from ordinary
source-local device recovery.

### Core Audio notification

Matching monitor events are logged with:

```text
default audio device changed
flow=...
role=...
endpoint_id=...
```

The capture boundary then logs:

```text
audio capture default device change signaled
endpoint_id=...
```

The monitored authoritative endpoints are:

```text
system_audio:
flow=eRender
role=eConsole

microphone:
flow=eCapture
role=eConsole
```

### Process-wide PortAudio refresh

The coordinated lifecycle emits:

```text
process-wide PortAudio refresh started
generation=N
```

and:

```text
process-wide PortAudio refresh completed
generation=M
```

`M` may be greater than `N`.

This is expected when additional Core Audio notifications arrive during the
same hardware/default-device transition.

For example:

```text
refresh started generation=6
...
refresh completed generation=9
```

means generations 6 through 9 were coalesced into one physical PortAudio
refresh.

It does not indicate four separate native restarts.

An immediately following second:

```text
process-wide PortAudio refresh started
```

for the same logical device transition may indicate insufficient notification
coalescing and should be investigated.

### Capture recovery

Each participating capture logs:

```text
audio capture recovery started reason=default_device_changed
```

followed by the newly selected device and:

```text
audio capture recovered
```

The expected order during coordinated refresh is:

```text
refresh started
        ↓
both captures enter recovery
        ↓
notification settling
        ↓
device selected source A
source A recovered
        ↓
device selected source B
source B recovered
        ↓
refresh completed
```

No source should select/reopen a native device during the coordinator's
pre-recreation settle period.

Doing so would violate the PortAudio full-teardown invariant.

### Source unavailable

Expected hardware/device discovery failures remain recoverable and use:

```text
audio capture recovery started reason=device_unavailable
audio capture recovery failed; retrying
    error_type=...
    error=...
    delay=...
```

A currently observed Windows/PyAudioWPatch condition when no usable WASAPI
input exists is:

```text
OSError(-9996, "Invalid device info")
```

This is an expected device-availability condition.

The application should remain alive.

Retry uses bounded exponential backoff.

A matching Core Audio default-device notification interrupts that backoff
immediately rather than waiting for the current retry delay.

### Device selection

Successful capture recreation logs the actual selected device:

```text
audio capture device selected
name=...
index=...
channels=...
sample_rate=...
```

Device indexes are diagnostic only.

They are transient PortAudio enumeration values and must not be interpreted
as stable identity.

The device name and native format are useful for confirming that recovery
followed the current Windows default.

### Capture health after refresh

At shutdown, inspect:

```text
frames_dropped
```

for each capture.

Real-device ADR-043 validation completed repeated Settings switches,
physical disconnect/reconnect, and unavailable-device recovery with:

```text
frames_dropped=0
```

on both sources.

Capture discontinuity logs should also appear for every processing path whose
native capture session was refreshed:

```text
capture discontinuity detected; resetting processing state
source=system_audio

capture discontinuity detected; resetting processing state
source=microphone
```