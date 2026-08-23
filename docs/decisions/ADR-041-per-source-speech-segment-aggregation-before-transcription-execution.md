# ADR-041: Per-Source Speech Segment Aggregation Before Transcription Execution

## Status

Accepted

## Date

2026-08-23

## Context

The service captures two independent audio sources:

```text
system_audio
microphone
```

Each source has its own real-time processing path:

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

The resulting speech segments are currently submitted directly to one shared
bounded `TranscriptionExecutor`.

ADR-036 established this execution boundary so that Whisper inference cannot
block real-time audio processing.

ADR-037 established bounded non-blocking submission and rejection of new
transcription work during sustained overload.

ADR-039 established two independent source pipelines converging on one shared
transcription executor.

The current architecture therefore behaves approximately as:

```text
system SpeechSegment ─────┐
                          │
                          ▼
                   TranscriptionExecutor
                          │
                          ▼
                       Whisper

microphone SpeechSegment ─┘
```

Realistic runtime measurements now show that the number and duration of
`SpeechSegment` values materially affect transcription throughput.

### Continuous dual-source workload

A controlled workload with long, nearly continuous speech produced:

```text
system_audio:
    avg_segment_duration = 9.816 s

microphone:
    avg_segment_duration = 4.630 s

total segments:
    214

rejected:
    7

rejection rate:
    approximately 3.3%
```

Despite the relatively efficient segment sizes, the shared executor still
reached full capacity:

```text
queue_high_water_mark = 10
avg_queue_wait = 17.853 s
max_queue_wait = 43.607 s
```

This demonstrated that a single transcription worker is itself close to the
available throughput limit during sustained dual-source speech.

### Natural conversation workload

A realistic two-person conversation produced:

```text
system_audio:
    segments_emitted = 171
    segments_rejected = 49
    avg_segment_duration ≈ 2.69 s

microphone:
    segments_emitted = 243
    segments_rejected = 57
    avg_segment_duration ≈ 3.45 s
```

Across both sources:

```text
segments_emitted = 414
segments_rejected = 106
segments_accepted = 308
```

The rejection rate was therefore approximately:

```text
25.6%
```

The accepted-segment count matched the 308 persisted transcript rows.

This confirms that the missing transcript data was caused by the explicit
bounded-overload policy rather than unexplained downstream loss.

The natural conversation also produced many small segments:

```text
segments < 1 second = 108 / 414
segments < 2 seconds = 218 / 414
segments < 3 seconds = 267 / 414
```

Approximately 64.5% of emitted transcription work items were therefore shorter
than three seconds.

Runtime evidence also shows that very short segments may require nearly as
much Whisper execution time as substantially longer segments.

Examples observed during testing include approximately:

```text
0.5-0.7 s audio
    ↓
~2.7-2.9 s inference
```

while many ten-second segments required approximately:

```text
~3-4 s inference
```

This demonstrates a significant fixed cost per transcription invocation.

The natural-conversation workload therefore creates inefficient executor
pressure:

```text
many small SpeechSegments
        ↓
many Whisper invocations
        ↓
fixed inference overhead repeated
        ↓
executor queue saturation
        ↓
segment rejection
```

The same natural-conversation test also demonstrated unstable language
detection on short fragments.

A primarily Romanian conversation containing smaller amounts of English,
Spanish, and Russian was frequently detected as unrelated languages.

Providing Whisper with more surrounding speech context may also improve
language-selection stability, although language policy remains a separate
future decision.

## Decision

### 1. Introduce a transcription-segment aggregation boundary

A new application-owned component named:

```text
TranscriptionSegmentAggregator
```

will be introduced between `SpeechSegmentAssembler` and
`TranscriptionExecutor`.

The resulting source pipeline becomes:

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
TranscriptionSegmentAggregator
    ↓
SpeechSegment
    ↓
TranscriptionExecutor
```

The aggregator operates only on already-completed `SpeechSegment` values.

It does not participate in:

- VAD;
- speech detection;
- pre-roll;
- post-roll;
- natural speech-boundary detection;
- maximum speech-segment splitting.

Those responsibilities remain owned by `SpeechSegmentAssembler`.

### 2. Aggregation is per source

Each `SpeechPipeline` owns its own independent
`TranscriptionSegmentAggregator`.

Therefore:

```text
system SpeechSegmentAssembler
        ↓
system TranscriptionSegmentAggregator
        ↓
                          ┐
                          │
                          ▼
                   shared executor

microphone SpeechSegmentAssembler
        ↓
microphone TranscriptionSegmentAggregator
        ↓
                          ┘
```

Segments from different sources are never combined.

This preserves:

- source identity;
- independent source timing;
- independent recovery boundaries;
- the multi-source architecture defined by ADR-039.

### 3. Preserve the existing `SpeechSegment` transcription contract

The aggregator will emit `SpeechSegment`.

It will not introduce a new transcription input type.

The existing contract remains:

```text
Transcriber.transcribe(
    SpeechSegment
) -> TranscriptionResult
```

The existing `TranscriptionWorkItem` also remains:

```text
source
+
SpeechSegment
```

This keeps aggregation invisible to the concrete transcription engine.

Faster-Whisper remains replaceable.

### 4. Aggregation is a transcription-execution concern

Aggregation configuration belongs under:

```yaml
transcription:
```

rather than:

```yaml
audio:
  segmentation:
```

This distinction is intentional.

`audio.segmentation` controls semantic speech-segment creation.

`transcription.aggregation` controls how those already-complete semantic units
are packaged for expensive transcription execution.

### 5. Short segments may be buffered

A completed speech segment does not necessarily need to be immediately
submitted to the executor.

A sufficiently short segment may be retained temporarily by the per-source
aggregator.

Subsequent nearby segments from the same source may be combined with it.

For example:

```text
SpeechSegment 0.7 s
      ↓
buffer

SpeechSegment 1.6 s
      ↓
combine

SpeechSegment 2.1 s
      ↓
combine
      ↓
one larger transcription segment
      ↓
TranscriptionExecutor
```

This reduces the number of Whisper invocations.

### 6. Long segments bypass unnecessary waiting

A segment that already satisfies the configured aggregation target does not
need to wait for another segment.

It may be emitted immediately.

The aggregator therefore does not intentionally add latency to already useful
large segments.

### 7. Aggregation has a bounded target and maximum duration

Aggregation will be configuration-driven.

The policy will define:

```text
target duration
maximum duration
maximum combinable gap
maximum buffering delay
```

The target duration represents a useful preferred transcription size.

The maximum duration is a hard bound.

If adding another segment would exceed the configured maximum:

```text
pending aggregate
        ↓
emit

incoming segment
        ↓
becomes next pending segment
```

The aggregator will not split an incoming completed `SpeechSegment`.

Maximum-duration speech splitting remains the responsibility of
`SpeechSegmentAssembler`.

### 8. Only temporally nearby segments may be combined

Two segments may only be aggregated if they belong to the same source and
their timeline gap is within a configured maximum.

Conceptually:

```text
segment A end
    ↓
small gap
    ↓
segment B start

→ may aggregate
```

but:

```text
segment A end
    ↓
long silence
    ↓
segment B start

→ emit A separately
→ begin new aggregate with B
```

The aggregator must not bridge arbitrarily long conversational silence.

### 9. Aggregated audio preserves timeline gaps

Aggregation will not simply concatenate speech samples back-to-back.

When two segments are separated by a valid positive timeline gap, the
aggregator will insert equivalent silence into the aggregated audio.

For example:

```text
segment A audio
    +
0.4 s timeline gap
    +
segment B audio
```

becomes:

```text
segment A audio
+
0.4 s zero-valued audio
+
segment B audio
```

This preserves the relationship between:

```text
segment timestamp
segment duration
audio duration
```

and retains a natural acoustic pause for the transcription engine.

### 10. Small timeline overlap must not duplicate audio

Adjacent segments may contain a very small overlap because of frame
quantization or boundary timing.

The aggregator must not duplicate overlapping audio.

When a small overlap occurs, the overlapping leading samples of the later
segment should be trimmed before concatenation.

A large or invalid overlap should be treated as a boundary rather than silently
combining inconsistent segments.

The exact overlap tolerance is an implementation detail derived from the
processing-frame resolution and does not require configuration unless runtime
evidence later demonstrates a need.

### 11. Buffering latency is bounded

The aggregator must never retain a completed segment indefinitely while
waiting for more speech.

A configured maximum buffering delay will force emission of pending work.

The pipeline already continuously receives normalized processing frames, even
while speech is absent.

The aggregator can therefore observe progression of the source audio timeline
and flush pending work when its buffering deadline is reached.

Aggregation must not introduce an asynchronous background task or independent
timer unless later required.

This keeps aggregation deterministic and tied to the existing source timeline.

### 12. Shutdown flushes pending aggregated speech

A graceful `SpeechPipeline.stop()` must flush any completed speech currently
held by the aggregator before the shared executor is stopped.

The lifecycle remains:

```text
stop source capture
        ↓
finish source pipeline
        ↓
flush pending transcription aggregate
        ↓
submit resulting work
        ↓
source pipeline stopped
        ↓
...
both sources stopped
        ↓
executor drains accepted work
        ↓
executor stopped
```

This preserves the lifecycle rule established by ADR-039:

> Sources stop producing transcription work before the shared executor drains.

### 13. Capture discontinuity must not cross aggregation state

A capture discontinuity defines a source continuity boundary.

Segments from before and after the discontinuity must never be aggregated
together.

Unlike the incomplete VAD/assembler state, a pending aggregation contains
already-completed valid speech.

Therefore, on discontinuity:

```text
pending aggregate
        ↓
flush and submit
        ↓
clear aggregation state
        ↓
reset normalizer / VAD / assembler
        ↓
process recovered audio
```

Completed speech is preserved where possible while continuity domains remain
separate.

### 14. Executor overload behavior remains unchanged

The aggregator does not replace ADR-037.

Once an aggregated `SpeechSegment` is emitted:

```text
TranscriptionWorkItem
        ↓
TranscriptionExecutor.submit()
```

still behaves as:

```text
accepted
    → bounded FIFO queue

rejected
    → return False
    → pipeline remains alive
```

Aggregation reduces the rate at which work is submitted.

It does not make the executor unbounded and does not retry rejected work.

### 15. Additional transcription workers remain a separate decision

This ADR does not change:

```text
worker_count = 1
```

The continuous-content test demonstrated that one worker may remain a genuine
capacity limit even after segment sizes improve.

However, aggregation will be implemented and measured first.

Only after measuring the reduced work-item rate will the project evaluate:

```text
one worker
vs.
additional workers
```

This prevents worker-count changes from hiding inefficient job production and
allows the effect of each change to be measured independently.

### 16. Aggregation must be observable

The aggregation boundary will expose enough statistics to compare the input
and output workload.

At minimum:

```text
segments_received
segments_emitted
segments_combined
```

Useful runtime diagnostics should also include:

```text
average emitted aggregate duration
maximum emitted aggregate duration
```

The existing `SpeechPipeline` statistics continue to describe semantic
segments emitted by `SpeechSegmentAssembler`.

The executor statistics continue to describe actual transcription work.

This allows comparison of:

```text
semantic segments
        ↓
aggregation reduction
        ↓
executor submissions
        ↓
executor rejection
```

## Initial configuration

The first implementation will use configuration-driven aggregation.

The proposed initial configuration is:

```yaml
transcription:
  queue_capacity: 10

  aggregation:
    enabled: true
    target_duration_seconds: 5.0
    max_duration_seconds: 10.0
    max_gap_seconds: 1.5
    max_wait_seconds: 2.0
```

These values are initial benchmark values, not permanent architectural
constants.

They are selected to:

- reduce the large number of sub-three-second transcription calls;
- preserve natural conversational pauses;
- avoid waiting unnecessarily for already-long segments;
- keep added latency bounded;
- remain within the segment durations already validated with Faster-Whisper.

They must be revisited using realistic conversation measurements.

## Resulting architecture

```text
                         system source

AudioCapture
    ↓
AudioNormalizer
    ↓
AudioVad
    ↓
SpeechSegmentAssembler
    ↓
TranscriptionSegmentAggregator
    ↓
TranscriptionWorkItem
    │
    └─────────────────────────────┐
                                  │
                                  ▼
                         TranscriptionExecutor
                                  │
                                  ▼
                              Transcriber
                                  │
                                  ▼
                         TranscriptRecorder


                       microphone source

AudioCapture
    ↓
AudioNormalizer
    ↓
AudioVad
    ↓
SpeechSegmentAssembler
    ↓
TranscriptionSegmentAggregator
    ↓
TranscriptionWorkItem
    │
    └─────────────────────────────┘
```

## Consequences

### Positive

#### Fewer Whisper invocations

Several short semantic segments may become one transcription request.

This directly attacks the fixed per-inference overhead observed during realistic
conversation testing.

#### Real-time processing remains non-blocking

Aggregation is lightweight in-memory processing.

Whisper execution remains isolated behind `TranscriptionExecutor`.

#### Semantic segmentation remains independent

VAD and the speech assembler do not need to become aware of Whisper throughput
or queue pressure.

#### Source identity remains clean

System and microphone audio are never aggregated together.

#### Existing transcriber contract remains stable

`Transcriber` continues to consume `SpeechSegment`.

No Faster-Whisper-specific type enters application contracts.

#### Language detection may receive better context

Longer audio inputs may reduce language ambiguity on extremely small speech
fragments.

This is a possible secondary benefit, not a replacement for a future explicit
language-policy decision.

#### Worker-count benchmarking becomes more meaningful

The service can first remove avoidable work before deciding how much execution
parallelism is genuinely required.

### Negative

#### Transcript availability is delayed slightly

Short completed speech may wait for another segment or for the configured
buffering deadline.

The maximum wait is explicitly bounded.

#### Aggregation introduces state

Each source now owns another small stateful processing component.

Its flush and discontinuity behavior must be tested carefully.

#### Aggregated transcript granularity becomes coarser

Multiple semantic speech turns may produce one persisted
`TranscriptionResult`.

This is an intentional trade-off for throughput and model context.

If finer transcript-level timing is required later, internal model subsegments
or post-processing would require a separate decision.

#### Silence must be synthesized

Preserving source timeline gaps requires inserting zero-valued samples.

This adds implementation complexity but keeps timestamp/audio-duration
semantics coherent.

#### Configuration requires benchmarking

Poor values could either:

- fail to reduce enough work; or
- introduce unnecessary transcription latency.

## Alternatives Considered

### Change `SpeechSegmentAssembler` to produce larger segments

Rejected.

The assembler owns semantic speech boundaries.

Its target duration is intentionally advisory, and natural `SpeechEnd` is
preferred.

Changing it primarily to satisfy Whisper throughput would mix:

```text
speech semantics
+
transcription execution optimization
```

inside one component.

### Increase transcription queue capacity

Rejected as the primary solution.

A larger queue increases tolerated backlog but does not increase processing
throughput.

It mainly trades:

```text
rejection
```

for:

```text
higher latency
```

during sustained overload.

### Immediately add a second Whisper worker

Deferred.

Runtime measurements show that additional execution capacity may eventually
be required.

However, natural conversation currently creates a large number of inefficient
short jobs.

Worker-count benchmarking should occur after avoidable job overhead is reduced.

### Aggregate segments inside `TranscriptionExecutor`

Rejected.

The executor owns:

- bounded scheduling;
- queueing;
- worker lifecycle;
- overload behavior.

Aggregation requires per-source temporal state and source-specific flush
semantics.

Putting this inside the shared executor would mix source-specific work
formation with shared execution scheduling.

### Aggregate system and microphone audio together

Rejected.

This would violate the multi-source architecture and lose clear speaker/source
identity.

It could also combine simultaneous participants into one audio stream before
transcription.

### Use an unbounded pending aggregation buffer

Rejected.

Aggregation state must remain bounded by duration and time.

The same bounded-resource principles that apply to the executor also apply
here.

### Remove silence between aggregated segments

Rejected.

Blindly concatenating speech would make the audio duration inconsistent with
the conversation timeline and could create unnatural word adjacency.

### Retry rejected aggregates

Rejected.

ADR-037 remains authoritative.

Retrying work during overload would add more work precisely when the executor
cannot keep up.

## Related Decisions

- ADR-022 — Shutdown and Lifecycle
- ADR-029 — Speech Segment Assembler Contract and State Machine
- ADR-030 — Transcription Boundary and Faster-Whisper Adapter
- ADR-031 — Speech Pipeline Orchestration and Transcription Scheduling
- ADR-035 — Audio Capture Discontinuity Propagation and Processing State Reset
- ADR-036 — Decouple Real-Time Audio Processing from Transcription Execution
- ADR-037 — Runtime Transcription Overload and Segment Rejection Policy
- ADR-039 — Multi-Source System and Microphone Audio Processing Architecture