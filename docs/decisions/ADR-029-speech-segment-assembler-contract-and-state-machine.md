# ADR-029: Speech Segment Assembler Contract and State Machine

## Status

Accepted

## Context

The audio transcription pipeline requires a component that converts normalized
20 ms processing frames and VAD state-transition events into complete
`SpeechSegment` objects.

The project deliberately separates speech detection from speech segmentation:

- `AudioVad` detects speech state transitions.
- `SpeechSegmentAssembler` owns semantic audio buffering and segment creation.

ADR-023 established this ownership boundary.

ADR-024 established the VAD output contract:

- normalized `ProcessingAudioFrame` input;
- discrete `SpeechStart` / `SpeechEnd` events;
- deterministic frame ordering;
- explicit VAD reset semantics.

ADR-025 established the high-level segmentation behavior:

- 200 ms pre-roll;
- 200 ms post-roll;
- approximately 3 second target duration;
- 5 second maximum duration;
- hard splitting at the maximum;
- no initial segment overlap;
- capture interruption terminates the current segment;
- shutdown discards an incomplete segment.

The assembler must therefore expose a small application-owned contract that is
independent of the VAD implementation and capture implementation.

## Decision

### 1. Application-owned contract

The application will define a `SpeechSegmentAssembler` protocol.

The assembler accepts one normalized processing frame together with the VAD
events observed while processing that frame.

The contract is:

    process(
        frame: ProcessingAudioFrame,
        events: tuple[SpeechStart | SpeechEnd, ...],
    ) -> tuple[SpeechSegment, ...]

    reset() -> None

    flush() -> tuple[SpeechSegment, ...]

The assembler must not depend on `AudioVad`, `SileroVADAdapter`, or any
capture implementation.

It consumes only project-owned audio and speech-event contracts.

### 2. `process()` semantics

`process()` represents one unit of normal streaming processing.

The frame and its events are treated as one atomic input.

A VAD event timestamp identifies the `ProcessingAudioFrame` in which the
transition becomes observable.

Therefore the assembler does not split an individual 20 ms frame at the event
timestamp.

The current frame remains available to the assembler when processing the
associated event.

`process()` may return zero or more completed segments.

Normally it returns zero or one segment. Multiple segments are permitted by the
contract so that hard-boundary processing does not artificially constrain
future implementations.

### 3. Idle state and pre-roll

While idle, the assembler maintains a bounded rolling buffer containing the
most recent audio up to the configured pre-roll duration.

The pre-roll buffer is discarded when no longer relevant.

When `SpeechStart` is observed while idle:

1. the retained pre-roll is included in the new segment;
2. the current frame is included;
3. the assembler enters the speaking state;
4. the idle pre-roll buffer is cleared.

Pre-roll is only applied when speech begins from the idle state.

Pre-roll does not carry across an already-active segment or a reset boundary.

### 4. Speaking state

While speaking, normalized frames are accumulated into the active segment.

The target duration is advisory.

Reaching the configured target duration does not itself cause a segment
boundary.

A natural `SpeechEnd` is preferred as the semantic boundary.

### 5. Natural speech end and post-roll

When `SpeechEnd` is observed while speaking:

1. the current frame remains available to the assembler;
2. the assembler enters the post-roll phase;
3. subsequent frames are collected until the configured post-roll duration
   has been satisfied;
4. the completed segment is emitted;
5. the assembler returns to the idle state.

Post-roll is only applied after a natural `SpeechEnd`.

### 6. Maximum duration

The configured maximum segment duration is a hard boundary.

When the active segment reaches the maximum duration:

1. the current segment is emitted immediately;
2. no overlap is introduced;
3. the assembler remains in the speaking state;
4. subsequent audio belongs to the next segment.

Continuous speech therefore produces consecutive non-overlapping segments.

The target duration is not a hard boundary.

### 7. `reset()` semantics

`reset()` represents a discontinuity in the input stream.

It is intended for events such as capture interruption or recovery where audio
continuity can no longer be assumed.

`reset()`:

- discards any active segment;
- discards post-roll state;
- discards pre-roll state;
- returns the assembler to the idle state;
- emits no segment.

The assembler must never produce a segment spanning audio across a reset
boundary.

`reset()` must not manufacture a `SpeechEnd` event.

### 8. `flush()` semantics

`flush()` represents normal pipeline shutdown.

`flush()`:

- discards any incomplete active segment;
- discards pending post-roll state;
- discards pre-roll state;
- returns the assembler to the idle state;
- emits no incomplete segment.

Calling `flush()` when the assembler is already idle is valid and returns an
empty tuple.

After `flush()`, the assembler may be reused for a new independent stream.

### 9. State machine

The assembler has three logical states:

    IDLE
    SPEAKING
    POST_ROLL

Transitions:

    IDLE
      |
      | SpeechStart
      v
    SPEAKING
      |
      | SpeechEnd
      v
    POST_ROLL
      |
      | post-roll satisfied
      v
    IDLE

From `SPEAKING`, reaching the maximum duration emits the current segment and
remains in `SPEAKING`.

From any state, `reset()` discards all state and returns to `IDLE`.

From any state, `flush()` discards all state and returns to `IDLE`.

### 10. Invariants

The assembler must maintain the following invariants:

1. Every emitted segment contains only normalized processing audio.
2. Every source frame belongs to at most one emitted segment.
3. Pre-roll is bounded by its configured duration.
4. Pre-roll is used only when speech begins from `IDLE`.
5. Post-roll is used only after a natural `SpeechEnd`.
6. No emitted segment exceeds the configured maximum duration.
7. Hard maximum splitting produces no overlap between adjacent segments.
8. No segment spans a reset/discontinuity boundary.
9. Shutdown never emits an incomplete segment.
10. The assembler owns the audio memory represented by emitted `SpeechSegment`
    objects through the existing `SpeechSegment` contract.
11. The assembler does not depend on the concrete VAD implementation.
12. The assembler operates only on normalized processing frames.

## Consequences

### Positive

- VAD and segmentation remain independently replaceable.
- The assembler can be tested entirely with deterministic synthetic frames and
  events.
- Capture recovery cannot accidentally create segments spanning discontinuous
  audio.
- Shutdown behavior is deterministic.
- Hard-duration splitting remains explicit and testable.
- Application-level padding remains owned by one component.
- The contract remains small enough for dependency injection and replacement.

### Negative

- The assembler maintains its own buffering and state.
- The pipeline must explicitly coordinate `reset()` when input continuity is
  lost.
- The distinction between target duration and maximum duration requires
  explicit tests to prevent accidental early splitting.
- Post-roll means a speech segment can remain temporarily incomplete after
  `SpeechEnd`.

## Alternatives Considered

### Let VAD produce complete speech segments

Rejected.

VAD is responsible for speech-state detection, not semantic audio buffering or
segment ownership.

### Make the assembler depend directly on `AudioVad`

Rejected.

This would couple segmentation to one VAD implementation and make replacement
or deterministic testing harder.

### Add capture-specific events to the assembler event stream

Rejected.

Capture interruption is an input-stream lifecycle concern rather than a speech
state event. `reset()` provides a cleaner boundary without coupling the
assembler to capture concepts.

### Use only `flush()` for discontinuities

Rejected.

Normal shutdown and unexpected input discontinuity have different semantic
meanings even though both discard incomplete state. Separate operations make
the lifecycle contract explicit.

### Split at the target duration

Rejected.

The target duration is an optimization/latency target, not a semantic speech
boundary. Natural `SpeechEnd` should be preferred until the hard maximum is
reached.