# ADR-030: Transcription Boundary and Faster-Whisper Adapter

## Status

Accepted

## Context

The audio pipeline now produces complete `SpeechSegment` objects through the
`SpeechSegmentAssembler`.

The next pipeline stage is speech-to-text transcription. The initial
implementation will use Faster-Whisper, but the application should not become
coupled to the concrete transcription library.

The project already establishes application-owned boundaries for audio
capture, normalization, VAD, and speech segment assembly. The transcription
stage should follow the same architecture.

The transcription pipeline also needs to remain independent from execution
and concurrency concerns. Faster-Whisper inference may be computationally
expensive, but deciding how transcription work is scheduled belongs to the
pipeline/application layer rather than to the transcription contract itself.

The Phase 1 project requirements call for a structured transcription result
containing:

* transcript text;
* detected language;
* confidence when available;
* timestamps.

The `SpeechSegment` already represents the semantic audio unit passed to
transcription, so exposing Faster-Whisper's internal subsegments through the
application boundary would unnecessarily couple the application contract to
the implementation.

## Decision

### 1. Application-owned transcription boundary

The application will define a `Transcriber` protocol.

The protocol accepts one complete `SpeechSegment` and synchronously returns
one application-owned `TranscriptionResult`.

The contract is:

```text
transcribe(segment: SpeechSegment) -> TranscriptionResult
```

The protocol must not depend on Faster-Whisper, CTranslate2, model objects,
tensors, or other implementation-specific types.

### 2. Segment-level transcription result

The application will represent the transcription result at the same semantic
granularity as the input `SpeechSegment`.

`TranscriptionResult` contains:

* `text`;
* `language`;
* optional `confidence`;
* `start`;
* `end`.

The result therefore represents the transcription of one complete speech
segment rather than exposing Faster-Whisper's internal subsegments.

The `start` timestamp corresponds to the source `SpeechSegment` timestamp and
the `end` timestamp is the segment start plus its duration.

### 3. Confidence

Confidence is optional because not every transcription implementation
necessarily provides a single application-level confidence value.

The application contract therefore represents confidence as:

```text
float | None
```

The contract does not prescribe how a concrete transcription implementation
derives a confidence value from model-specific output.

### 4. Synchronous contract

`Transcriber.transcribe()` is synchronous.

The transcriber is responsible for converting one `SpeechSegment` into one
`TranscriptionResult`.

The application/pipeline layer is responsible for deciding how transcription
work is scheduled, including whether it is executed:

* directly;
* in a worker thread;
* through a queue;
* concurrently;
* or through another future execution mechanism.

This keeps model execution concerns separate from the application contract.

### 5. Faster-Whisper isolation

Faster-Whisper will be introduced behind the `Transcriber` boundary.

The future implementation may use:

```text
SpeechSegment
      ↓
Transcriber
      ↓
FasterWhisperTranscriber
      ↓
Faster-Whisper
      ↓
TranscriptionResult
```

No application component outside the concrete adapter should depend directly
on Faster-Whisper types.

The Faster-Whisper model will be created once during application composition
and reused for subsequent transcription requests.

### 6. Result invariants

`TranscriptionResult` must maintain these invariants:

1. `start` must not be negative.
2. `end` must not be earlier than `start`.
3. `confidence`, when present, must be within the normalized range `0.0` to
   `1.0`.
4. `language`, when represented, must be a valid non-empty language identifier.
5. The result represents one source `SpeechSegment`.
6. The result does not expose model-specific subsegment types.

### 7. Responsibilities

The transcription boundary owns:

* conversion from a `SpeechSegment` to a transcription result;
* model-specific transcription behavior inside concrete implementations.

The pipeline owns:

* scheduling;
* concurrency;
* ordering;
* lifecycle;
* retry/recovery policy.

The storage layer will later own persistence of completed transcription results.

## Consequences

### Positive

* Faster-Whisper remains replaceable.
* The application contract is independent of external ML libraries.
* Tests can use a fake `Transcriber` without loading a model.
* Transcription execution can evolve independently from the domain contract.
* The semantic unit remains consistent from `SpeechSegment` to
  `TranscriptionResult`.
* Model-specific subsegments do not leak into the rest of the application.

### Negative

* The application result initially exposes less detail than Faster-Whisper
  can potentially provide.
* A future requirement for word-level or model-subsegment timestamps will
  require an explicit contract extension.
* Pipeline scheduling must be implemented separately.

## Alternatives Considered

### Expose Faster-Whisper directly

Rejected.

This would couple the application to the initial transcription implementation
and make replacement or deterministic testing harder.

### Return Faster-Whisper's native segment objects

Rejected.

Those objects are implementation-specific and would leak the transcription
library across the architectural boundary.

### Return Whisper subsegments from the application contract

Rejected for the initial implementation.

The application currently treats `SpeechSegment` as the semantic unit to
transcribe. Exposing internal model segmentation would add complexity without
a current requirement.

### Make the transcriber asynchronous

Rejected for the initial contract.

Model execution may eventually need asynchronous scheduling, but that is a
pipeline concern. Keeping the transcriber synchronous gives it a small,
deterministic responsibility and avoids coupling model execution to the
application's concurrency model.

### Include scheduling or worker behavior in `Transcriber`

Rejected.

Execution and concurrency are orchestration concerns and should remain outside
the replaceable transcription component.

## Related Decisions

* ADR-005: Architectural Boundaries
* ADR-016: Application Composition Root
* ADR-021: Audio Normalization
* ADR-023: VAD and Speech Buffer Semantics
* ADR-028: Voice Activity Detection Architecture and Silero Boundary
* ADR-029: Speech Segment Assembler Contract and State Machine

## Superseded aspects

ADR-045 extends the transcription call with an optional explicit language
selection while preserving the synchronous, application-owned, source-agnostic
`Transcriber` boundary:

```python
transcribe(
    segment: SpeechSegment,
    *,
    language: str | None = None,
) -> TranscriptionResult
```

Language state and multilingual switching policy remain outside the concrete
transcriber.
