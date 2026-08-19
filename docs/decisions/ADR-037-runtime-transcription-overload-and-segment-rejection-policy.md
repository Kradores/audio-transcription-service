# ADR-037: Transcription Runtime Overload and Rejection Policy

## Status
**Accepted**

## Context

The transcription stage depends heavily on the capabilities and current workload of the user's PC.

Faster-Whisper may normally process speech faster than it is produced, but this cannot be guaranteed. Runtime conditions such as:

* CPU saturation;
* insufficient available RAM;
* other applications consuming system resources;
* thermal throttling;
* slower CPUs;
* different Whisper models/configurations;
* temporary OS scheduling pressure;

can cause transcription to become slower than real-time audio production.

Previously, transcription was performed directly from `SpeechPipeline`:

```text
SpeechPipeline
    │
    └── await Whisper
```

This caused the pipeline to stop consuming audio while transcription was running. Under sufficient transcription latency, the capture queue could fill and audio frames could be dropped.

The transcription executor introduced by the previous architectural work separates these responsibilities:

```text
SpeechPipeline
    │
    └── submit(segment)
             │
             ▼
       bounded queue
             │
             ▼
          worker
             │
             ▼
          Whisper
```

The executor deliberately uses a bounded queue.

Therefore, when transcription is slower than speech production for long enough, the queue will eventually become full.

## Problem

We need to define what happens when the transcription executor cannot accept another speech segment.

This is not an exceptional application failure. It is a normal runtime overload condition caused by the available processing capacity being temporarily lower than the workload.

We therefore need a policy that:

1. never blocks the real-time audio-processing pipeline;
2. never allows unbounded transcription memory growth;
3. keeps the service alive under overload;
4. makes rejected work observable;
5. does not attempt uncontrolled retries;
6. does not treat overload as a transcription-engine failure;
7. leaves room for future adaptive/backpressure policies.

---

# Decision

## 1. The transcription queue remains bounded

The executor owns a bounded `asyncio.Queue`.

Its capacity is configuration-driven:

```yaml
transcription:
  queue_capacity: 10
```

The queue capacity represents the maximum amount of **accepted but not yet completed transcription work** waiting behind the active transcription operation.

The queue must not become unbounded.

---

## 2. Submission is non-blocking

`TranscriptionExecutor.submit()` remains synchronous:

```python
def submit(self, segment: SpeechSegment) -> bool:
```

The caller must never wait for queue space.

The semantics are:

```text
True
 └── segment accepted

False
 └── segment rejected because executor cannot accept it
```

This is essential because `SpeechPipeline` is part of the real-time audio-processing path.

It must be able to continue processing subsequent audio frames regardless of transcription capacity.

---

## 3. Queue saturation is not an exception

`TranscriptionQueueFullError` is removed entirely.

A full queue is expected runtime behavior.

The executor handles it internally:

```text
queue full
    │
    ▼
submit() → False
```

The rejection itself does not propagate an exception into `SpeechPipeline`.

This keeps overload separate from actual transcription failures.

---

## 4. Rejected segments are dropped

When `submit()` returns `False`, the segment is considered rejected and is not retried.

The initial policy is therefore:

> **Drop the segment when the transcription executor is saturated.**

There is deliberately no retry queue, delayed retry, or secondary unbounded buffer.

This provides a hard upper bound on memory consumption and ensures that overload cannot cascade into progressively increasing latency.

The distinction is important:

```text
accepted segment
    ↓
queue
    ↓
Whisper
    ↓
result
```

versus:

```text
rejected segment
    ↓
discarded
```

We accept that transcription completeness may degrade under sustained resource pressure in exchange for keeping the real-time processing path healthy.

---

## 5. Rejection is observable

`SpeechPipeline` maintains a runtime counter:

```python
segments_rejected
```

The counter is incremented whenever:

```python
transcription_executor.submit(segment) is False
```

This gives us visibility into overload without turning overload into an application failure.

The final pipeline statistics therefore distinguish:

```text
segments_emitted
segments_rejected
transcriptions_completed
```

For example:

```text
segments_emitted=20
segments_rejected=7
transcriptions_completed=13
```

This is materially more useful than simply reporting that "some transcriptions were lost."

---

## 6. Rejection is logged

The executor logs queue saturation as a warning-level runtime event.

The pipeline may additionally record the rejected segment in its statistics.

We should avoid logging every subsequent frame while the queue remains full.

The important event is:

```text
transcription executor overloaded
```

with useful context such as configured queue capacity.

The statistics provide the aggregate count.

This gives us both:

* an immediate operational signal;
* cumulative runtime visibility.

---

## 7. Transcription failures remain different from overload

A transcription engine failure is not equivalent to queue saturation.

### Overload

```text
queue full
    ↓
submit() → False
    ↓
segment rejected
    ↓
pipeline continues
```

### Transcription failure

```text
segment accepted
    ↓
worker
    ↓
Whisper
    ↓
exception
    ↓
worker logs failure
    ↓
worker continues with next segment
```

The executor therefore continues to isolate individual transcription failures from the worker lifecycle.

---

## 8. No automatic retry

Rejected segments are not retried.

This is intentional.

Suppose Whisper requires 6 seconds to process a segment while speech produces a new segment every 3 seconds:

```text
production:   |---3s---|---3s---|---3s---|---3s---|

processing:   |------6s------|
                    |------6s------|
```

Retrying rejected segments would only increase the amount of work waiting to be processed.

Under sustained overload, retries would turn a bounded queue into effectively unbounded pending work.

The service would eventually trade dropped transcription for:

* increased memory usage;
* increased latency;
* stale transcripts;
* larger queues;
* potentially system-wide instability.

That is explicitly rejected.

---

# Consequences

## Positive consequences

### Real-time processing remains independent of Whisper

The pipeline can continue:

```text
capture
  ↓
normalization
  ↓
VAD
  ↓
segmentation
  ↓
submit()
  ↓
continue processing audio
```

without waiting for transcription.

### Memory usage is bounded

The executor queue has a fixed capacity.

### The service survives sustained overload

The service does not crash simply because the machine cannot keep up with transcription.

### Overload is observable

We can distinguish:

```text
segments emitted
segments rejected
transcriptions completed
```

which gives us an important runtime health signal.

### The policy is replaceable

The executor boundary allows future policies without coupling them directly to audio capture or VAD.

For example, future versions could introduce:

* adaptive queue sizing;
* priority-based transcription;
* segment coalescing;
* degradation to a smaller Whisper model;
* configurable overload behavior;
* user-visible overload notifications;
* external transcription execution.

None of those are required by this ADR.

---

## Negative consequences

### Some speech may not be transcribed

Under sustained overload, segments will be rejected.

This is an intentional trade-off.

The system prioritizes:

> **keeping real-time audio processing alive over guaranteeing transcription of every segment.**

### Transcription may become incomplete

A user may see missing transcript portions when the machine is overloaded.

This is why rejection must remain observable.

### Queue capacity becomes an important configuration parameter

A queue that is too small may reject work prematurely.

A queue that is too large may tolerate longer overload periods but increase transcription latency and memory usage.

The initial value is:

```yaml
transcription:
  queue_capacity: 10
```

The appropriate value can be revisited based on runtime measurements.

---

# Rejected alternatives

## Block `submit()` until capacity becomes available

Rejected.

This would reintroduce the original problem:

```text
SpeechPipeline
    ↓
submit()
    ↓
WAIT
    ↓
queue space
```

Eventually the pipeline stops consuming audio and capture-side buffering can overflow.

---

## Use an unbounded queue

Rejected.

An unbounded queue simply moves the overload problem from:

```text
queue full
```

to:

```text
memory growth + increasing latency
```

It provides no meaningful capacity guarantee.

---

## Raise `TranscriptionQueueFullError`

Rejected.

Queue saturation is a normal runtime overload condition, not an exceptional application state.

Exceptions are reserved for actual failures.

---

## Retry rejected segments

Rejected.

Retries increase work during the exact condition in which the system is already unable to keep up.

---

## Drop the oldest queued segment instead of rejecting the newest

Not selected for the initial implementation.

This could potentially be useful for real-time systems where recent speech has greater value than older speech, but it introduces additional queue semantics and should be a separate design decision.

The current policy is simpler:

> **FIFO bounded queue + reject new submissions when full.**

---

## Block capture or apply backpressure to the audio pipeline

Rejected.

The audio pipeline is responsible for keeping up with the capture stream. Transcription capacity must not be allowed to dictate whether audio can continue being consumed.

---

# Resulting architecture

The runtime behavior is now explicitly:

```text
                    ┌─────────────────────┐
                    │   SpeechPipeline    │
                    │                     │
AudioCapture ──────►│ VAD → Segmentation  │
                    │          │          │
                    │          ▼          │
                    │       submit()      │
                    └──────────┬──────────┘
                               │
                         ┌─────▼─────┐
                         │  Bounded  │
                         │   Queue   │
                         └─────┬─────┘
                               │
                         ┌─────▼─────┐
                         │  Worker   │
                         └─────┬─────┘
                               │
                         asyncio.to_thread
                               │
                         ┌─────▼─────┐
                         │  Whisper  │
                         └─────┬─────┘
                               │
                         TranscriptionResult
                               │
                               ▼
                          TranscriptRecorder
```

When overloaded:

```text
SpeechSegment
      │
      ▼
   submit()
      │
      ├──── True ──► bounded queue ──► Whisper
      │
      └──── False
             │
             ├── segments_rejected += 1
             ├── warning log
             └── segment discarded
```

And critically:

```text
                    overload
                       │
                       ▼
              transcription degraded
                       │
                       │
                       ▼
             audio processing continues
```

rather than:

```text
                    overload
                       │
                       ▼
              audio processing blocks
                       │
                       ▼
                capture queue fills
                       │
                       ▼
                 audio dropped
```
