# ADR-035 — Audio Capture Discontinuity Propagation and Processing-State Reset

## Status
Accepted

## Context

ADR-019 establishes that `AudioCapture` must recover transparently from temporary audio-device loss while keeping the `frames()` stream alive. A recovery can nevertheless break the continuity assumptions of stateful downstream processing components.

`AudioNormalizer` maintains buffered/resampler state. `AudioVad` maintains VAD state. `SpeechSegmentAssembler` maintains speech-segmentation state. These states must not cross a capture discontinuity.

The existing `AudioFrame` contract must remain independent of capture lifecycle semantics, and `frames()` must continue to expose only audio frames.

## Decision

`AudioCapture` will expose a registered synchronous discontinuity callback:

```python
set_discontinuity_handler(handler: Callable[[], None]) -> None
```

`AudioCapture` is responsible for detecting capture discontinuities and invoking the registered handler.

The callback is notification-only. It must return without awaiting downstream processing or directly mutating processing components.

`SpeechPipeline` owns coordination of the resulting reset.

Before processing the first recovered audio frame, the pipeline resets processing state in upstream-to-downstream order:

```text
AudioNormalizer.reset()
AudioVad.reset()
SpeechSegmentAssembler.reset()
```

A capture discontinuity discards any incomplete speech segment. No synthetic `SpeechEnd` is emitted and no incomplete segment is transcribed solely because of the discontinuity.

`AudioFrame` is unchanged.

`AudioCapture.frames()` remains:

```python
AsyncIterator[AudioFrame]
```

Capture-specific information such as device identity, recovery attempts, and device changes remains within the capture/observability boundary.

The discontinuity handler is registered before capture startup and is not dynamically replaced while capture is running.

## Consequences

### Positive

* Preserves the existing `AudioFrame` contract.
* Preserves the existing `frames()` async-iterator contract.
* Keeps capture recovery independent of downstream processing.
* Makes `SpeechPipeline` the sole coordinator of cross-component reset.
* Prevents normalizer, VAD, and assembler state from crossing capture boundaries.
* Avoids asynchronous coupling between capture recovery and pipeline execution.
* Keeps the mechanism small and replaceable.

### Negative

* Adds a lifecycle callback to `AudioCapture`.
* Adds `reset()` to the stateful processing components where required.
* Requires pending-discontinuity handling in `SpeechPipeline`.
* Adds concurrency/lifecycle tests around callback delivery.

## Alternatives considered

1. **Discontinuity field on `AudioFrame`** — rejected because capture lifecycle semantics would leak into the generic audio-frame contract.
2. **Timestamp-gap detection** — rejected because timestamp gaps are not an authoritative indication of device discontinuity.
3. **`AudioFrame | AudioCaptureEvent` from `frames()`** — rejected because it weakens the existing frame-stream contract.
4. **Capture generation/session ID on every frame** — rejected for the same boundary-leakage reason.
5. **Direct reset from `AudioCapture`** — rejected because capture must not depend on or coordinate VAD, normalizer, or assembler state.
6. **Flush incomplete state at discontinuity** — rejected because an interruption is not a natural speech boundary and old buffered state must not cross into the new continuity domain.
7. **Restart the entire `SpeechPipeline`** — rejected because capture recovery should remain independent of pipeline lifecycle.
8. **Separate discontinuity async event stream** — rejected because the event is rare and one-way, while introducing a second asynchronous stream would add unnecessary coordination complexity.

## Related decisions

* ADR-018 — Audio Capture Architecture
* ADR-019 — Audio Capture Recovery
* ADR-020 — Audio Ownership Boundaries
* ADR-021 — Audio Normalization
* ADR-022 — Shutdown and Lifecycle
* ADR-028 — Voice Activity Detection Architecture and Silero Boundary
* ADR-029 — Speech Segment Assembler Contract and State Machine
* ADR-031 — Speech Pipeline Orchestration and Transcription Scheduling
