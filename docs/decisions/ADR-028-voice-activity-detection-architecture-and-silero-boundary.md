# ADR-028: Voice Activity Detection Architecture and Silero Boundary

## Status
Accepted

## Context/Reason

The audio pipeline requires Voice Activity Detection (VAD) to identify
speech boundaries before audio is passed to the speech segmentation and
transcription stages.

The project currently uses Silero VAD as the initial VAD implementation.

VAD is a stateful processing concern. It must observe a sequence of normalized
20 ms processing frames and determine when speech starts and ends.

The application should not depend directly on Silero-specific APIs, model
objects, tensors, or implementation details. The VAD implementation should
therefore be replaceable without requiring changes to the rest of the audio
pipeline.

The project also has a configurable audio processing format. The normalizer
is responsible for converting native capture audio into the configured
processing format, including channel conversion, sample-rate conversion,
sample-type conversion, buffering, and exact 20 ms framing.

Silero supports 8 kHz and 16 kHz.
Our application currently standardizes on 16 kHz mono.

Silero VAD currently requires:

- mono audio;
- float32 samples;
- 20 ms processing frames.

The processing format therefore needs to remain configurable while the current
Silero VAD establishes the format compatibility requirement at the VAD
boundary.

VAD must also remain separate from speech segment assembly. VAD determines
speech state transitions, while the downstream `SpeechSegmentAssembler`
owns semantic buffering, pre-roll, post-roll, segment boundaries, and
maximum-duration splitting.

## Decision

The application will define an application-owned `AudioVad` protocol as the
boundary between normalized audio processing and VAD implementation.

The protocol accepts `ProcessingAudioFrame` objects and emits zero or one
speech state transition per processed frame.

The supported events are:

- `SpeechStart`
- `SpeechEnd`

The protocol will expose the following operations:

- `process(frame)` — process one normalized 20 ms frame and emit any speech
  state transition;
- `reset()` — discard VAD state and return the VAD to its initial non-speech
  state.

The VAD is stateful.

Continuous speech does not produce repeated `SpeechStart` events, and
continuous silence does not produce repeated `SpeechEnd` events.

A single processing frame can produce at most one transition event.

VAD event timestamps use the timestamp of the `ProcessingAudioFrame` in which
the transition becomes observable.

`reset()` does not emit a `SpeechEnd` event if the VAD was previously in the
speaking state. It is a lifecycle operation that simply returns the VAD to
the initial non-speech state.

The current Silero VAD implementation will require the processing format at
the VAD boundary to be:

- 16 kHz;
- mono;
- float32;
- exactly 20 ms.

`AudioProcessingSettings` remains the source of truth for the configurable
processing sample rate and channel count. The generic processing contract
will not be changed to hard-code Silero requirements.

The current application configuration must therefore select a processing
format compatible with Silero VAD.

Audio format conversion and resampling remain responsibilities of
`AudioNormalizer`. The Silero adapter must not introduce a second general
audio normalization or resampling pipeline.

Silero-specific implementation details remain encapsulated within the
Silero VAD adapter, including:

- model state;
- model-specific buffering;
- model-specific windowing;
- tensor conversion;
- Silero inference;
- model-specific state management.

The rest of the application depends only on the `AudioVad` protocol and
project-owned speech event contracts.

## Rationale

### Application-owned abstraction

An application-owned protocol prevents Silero-specific concepts from leaking
into the rest of the system.

This allows the VAD implementation to be replaced with another model or
algorithm without changing downstream components.

### Stateful VAD

Speech detection depends on transitions over time rather than independent
classification of individual frames.

Keeping state inside the VAD implementation allows it to handle speech
thresholds, silence duration, model context, and other temporal behavior
without exposing those implementation details to the rest of the pipeline.

### Existing speech events

`SpeechStart` and `SpeechEnd` already represent the semantic transitions
required by the downstream speech segmentation stage.

Introducing another intermediate event abstraction would add complexity
without providing a current architectural benefit.

### Processing format boundary

The normalizer already owns audio format conversion and streaming resampling.

Keeping Silero's format requirement at the VAD boundary avoids duplicating
audio conversion logic inside the VAD adapter.

At the same time, keeping `AudioProcessingSettings` generic preserves the
ability to adapt the processing pipeline to another VAD implementation with
different format requirements in the future.

### VAD and segmentation separation

VAD determines when speech starts and ends.

`SpeechSegmentAssembler` remains responsible for:

- pre-roll;
- post-roll;
- semantic buffering;
- segment boundaries;
- maximum-duration splitting;
- `SpeechSegment` creation.

This prevents model-specific VAD behavior from becoming coupled to speech
segment construction.

## Consequences

### Positive

- Silero is isolated behind an application-owned boundary.
- The VAD implementation is replaceable.
- VAD state remains encapsulated.
- Speech events have deterministic timestamps.
- Audio normalization remains owned by `AudioNormalizer`.
- The processing format remains configuration-driven.
- Unit tests can remain independent of the Silero model.
- Speech detection and speech segmentation remain separate responsibilities.

### Negative

- The VAD abstraction introduces another application-owned interface.
- Silero's format requirements constrain the processing configuration while
  Silero is the active VAD implementation.
- A future VAD with different input requirements may require changes to the
  processing configuration or pipeline boundary.
- The Silero adapter must translate normalized processing frames into the
  model's required representation.

## Alternatives Considered

### Expose Silero directly to the application

Rejected because it would couple the application to a specific external ML
implementation and make replacement more difficult.

### Return a boolean speech decision

Rejected because downstream components need speech transitions rather than
only the current classification of each frame.

### Introduce a generic `VadResult` event

Rejected because the existing `SpeechStart` and `SpeechEnd` contracts already
represent the required semantic transitions.

### Perform resampling inside the Silero adapter

Rejected because audio normalization and resampling are already owned by
`AudioNormalizer`. Duplicating this responsibility would make the pipeline
harder to reason about and test.

### Hard-code 16 kHz mono in `ProcessingAudioFrame`

Rejected because `AudioProcessingSettings` intentionally provides a
configuration-driven processing format. The generic processing contract
should not become coupled to the current VAD implementation.

### Combine VAD and speech segmentation

Rejected because VAD and semantic speech buffering have different
responsibilities. The VAD identifies transitions; the segment assembler owns
speech buffering and segment boundaries.

## Related Components

- `AudioVad`
- `ProcessingAudioFrame`
- `SpeechStart`
- `SpeechEnd`
- `AudioNormalizer`
- `AudioProcessingSettings`
- `SpeechSegmentAssembler`
- `SileroVADAdapter`
- ADR-027: Configurable Audio Processing Format