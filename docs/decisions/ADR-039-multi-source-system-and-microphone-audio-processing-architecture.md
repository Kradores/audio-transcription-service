# ADR-039: Multi-Source System and Microphone Audio Processing Architecture

## Status
- **Accepted**
- **Date:** 2026-08-19

## Context

The service currently captures Windows system audio through WASAPI loopback and processes it through the following real-time path:

```text
AudioCapture
    ↓
AudioNormalizer
    ↓
AudioVad
    ↓
SpeechSegmentAssembler
    ↓
TranscriptionExecutor
    ↓
Transcriber
    ↓
TranscriptRecorder
    ↓
TranscriptRepository
```

This is sufficient for transcribing audio played by the computer, such as the remote participant in a voice or video call.

It is not sufficient for capturing a complete conversation.

The local participant's speech is normally captured by a microphone and is not part of the WASAPI loopback stream. The service therefore needs to capture and transcribe both:

- Windows system audio;
- microphone audio.

The existing real-time processing components are stateful. In particular, normalization, VAD, and speech-segment assembly maintain state across consecutive audio frames. Capture discontinuities reset this state so audio from different continuous streams is not incorrectly joined.

The existing architecture also deliberately separates real-time audio processing from transcription execution. `TranscriptionExecutor` provides bounded asynchronous execution so slower Whisper transcription cannot block the real-time capture and processing path.

Adding a second audio source must preserve these properties while also allowing transcripts from both sources to be reconstructed on a common conversation timeline.

## Decision

The service will use **two independent real-time audio processing paths**, one for system audio and one for microphone audio.

The two paths will converge only after source-specific speech segmentation, at the shared transcription execution boundary.

Conceptually:

```text
System Audio Capture
        ↓
AudioNormalizer
        ↓
AudioVad
        ↓
SpeechSegmentAssembler
        ↓
source-tagged transcription work
        ┐
        │
        ▼
shared TranscriptionExecutor
        ↓
shared Transcriber
        ↓
source-tagged transcription result
        ↓
TranscriptRecorder
        ↓
TranscriptRepository
        ↑
        │
        ┘
source-tagged transcription work
        ↑
SpeechSegmentAssembler
        ↑
AudioVad
        ↑
AudioNormalizer
        ↑
Microphone Capture
```

The two audio sources will **not be mixed into a single audio stream** before VAD, segmentation, or transcription.

## Source-specific processing state

Each audio source will own independent instances of its stateful real-time processing components.

Conceptually:

```text
System audio
    ├── AudioCapture
    ├── AudioNormalizer
    ├── AudioVad
    └── SpeechSegmentAssembler

Microphone
    ├── AudioCapture
    ├── AudioNormalizer
    ├── AudioVad
    └── SpeechSegmentAssembler
```

Stateful processing components will not be shared between the two sources.

This ensures that:

- VAD state from one source cannot affect the other;
- normalization/resampling state remains stream-specific;
- segmentation decisions remain source-specific;
- a discontinuity in one source does not corrupt the processing state of the other;
- recovery of one audio device does not unnecessarily interrupt the other source.

A discontinuity will reset only the stateful processing path associated with the affected source.

## Native capture resource ownership

System-audio and microphone capture will own independent native capture sessions and resources.

In particular, they will not depend on shared ownership of a single PyAudio instance.

This preserves failure and recovery isolation.

For example, system-output recovery may require destroying and recreating the native PyAudio session so Windows default-output device changes are rediscovered correctly. That recovery must not destroy an active microphone capture session.

The same principle applies in the opposite direction when microphone capture requires recovery.

## Shared transcription execution

Both source-specific processing paths will submit completed speech segments to **one shared `TranscriptionExecutor`**.

The executor will continue to provide:

- bounded work capacity;
- non-blocking submission from real-time processing;
- observable overload;
- graceful draining of accepted work during shutdown.

Initially, transcription will continue to use one shared Whisper worker/model execution path.

The architecture will not introduce one transcription worker per audio source.

This avoids increasing CPU, GPU, and memory pressure merely because another capture source exists and preserves the overload protection established for transcription execution.

The executor queue represents the combined transcription workload from all audio sources.

The existing reject-newest overload policy remains applicable initially. Per-source prioritization or fairness scheduling is not introduced by this decision.

Observability must allow transcription submissions and rejections to be attributed to their source so overload affecting one side of a conversation can be diagnosed.

## Transcription executor lifecycle ownership

Source-specific processing pipelines will use the shared `TranscriptionExecutor` but will not independently own its lifecycle.

A higher-level conversation orchestration component will own shared transcription execution and coordinate the source pipelines.

Conceptually:

```text
Application
    ↓
ConversationPipeline
    ├── shared TranscriptionExecutor
    │
    ├── System SpeechPipeline
    │       ├── capture
    │       ├── normalizer
    │       ├── VAD
    │       └── assembler
    │
    └── Microphone SpeechPipeline
            ├── capture
            ├── normalizer
            ├── VAD
            └── assembler
```

The exact component name may change during implementation; the architectural responsibility is the important part.

Startup is conceptually:

```text
start shared TranscriptionExecutor
start system-audio processing path
start microphone processing path
```

Shutdown is conceptually:

```text
stop system-audio processing path
stop microphone processing path
stop shared TranscriptionExecutor
    ↓
drain all previously accepted transcription work
```

This guarantees that no source can independently stop the shared executor while another source is still producing work.

Startup and failure handling must also clean up already-started resources when later startup steps fail.

## Audio source identity

The system must preserve which audio source produced each transcript.

At minimum, the model must distinguish:

```text
SYSTEM_AUDIO
MICROPHONE
```

Source identity is orchestration metadata.

It will **not** be added to low-level audio-processing contracts solely for routing purposes.

In particular:

- `AudioFrame` remains source-agnostic;
- `ProcessingAudioFrame` remains source-agnostic;
- `AudioNormalizer` remains source-agnostic;
- `AudioVad` remains source-agnostic;
- `SpeechSegmentAssembler` remains source-agnostic;
- `Transcriber` remains source-agnostic.

The containing source-specific processing path already knows the origin of its audio.

Source identity will therefore be attached when a completed `SpeechSegment` crosses from source-specific real-time processing into shared transcription execution.

Conceptually:

```text
SpeechSegment
    +
AudioSource
    ↓
source-tagged transcription work
```

The exact application-level contract and type names will be determined during implementation.

The existing transcriber responsibility remains conceptually:

```text
SpeechSegment → TranscriptionResult
```

Whisper does not need to know whether audio originated from the microphone or system loopback.

Source identity must instead accompany the result through the application layer until persistence.

## Persistence

Persisted transcripts must retain their audio source.

The transcript schema will therefore distinguish at least:

```text
system_audio
microphone
```

This allows persisted data to be reconstructed as a conversation rather than an undifferentiated stream of transcript text.

The project is currently in development and the transcript database is disposable.

No database migration framework or schema-versioning mechanism is introduced as part of this decision.

The existing table-creation SQL will be updated for the new schema. Existing development databases may be deleted and recreated when the schema changes.

A production-grade migration strategy may be introduced later when preserving existing database contents becomes a requirement.

## Shared conversation timeline

Both capture sources must produce timestamps relative to **one shared monotonic conversation timeline**.

Independent capture-local timelines starting at zero are insufficient.

For example, if system capture begins first and microphone capture becomes active 350 ms later, the microphone's first frame must not incorrectly appear to have occurred at the same conversation time as the system capture's first frame.

Conceptually:

```text
Conversation/session start
          ↓
shared monotonic timeline
        ┌─┴─┐
        │   │
     system microphone
        │   │
        ▼   ▼
 comparable timestamps
```

Each capture source may use its native callback timing internally, but that timing must be mapped onto the shared conversation timeline.

The timeline must:

- use a monotonic clock rather than wall-clock time for audio timing;
- preserve real startup offsets between sources;
- continue across temporary capture-device recovery;
- not reset to zero when a source reconnects;
- make timestamps from different sources meaningfully comparable.

Sample-perfect synchronization is not required.

The required guarantee is that approximately equal timestamps from different sources represent approximately the same point in the conversation.

## Recovery and failure isolation

Expected capture-device problems are handled independently per source.

For example:

```text
system output unavailable
        ↓
system capture recovery
        ↓
system processing-state reset

microphone continues normally
```

and:

```text
microphone unavailable
        ↓
microphone capture recovery
        ↓
microphone processing-state reset

system capture continues normally
```

Temporary absence or replacement of one audio device must not terminate the other capture path.

Unexpected failures in application processing components are different from expected device availability problems.

Unexpected processing failures must be surfaced to the higher-level orchestration rather than silently leaving the application permanently recording only one side of the conversation.

Further microphone-specific device discovery and recovery policy will be defined separately.

## Conversation ordering

Persistence insertion order is not the authoritative conversation order.

With independent source pipelines, segments may complete in a different order from when their speech began.

For example:

```text
System segment:
    start = 10.0
    end   = 15.0

Microphone segment:
    start = 12.0
    end   = 13.0
```

The microphone segment may be submitted and persisted first because it completes earlier.

Therefore:

```text
database insertion order ≠ conversation order
```

Conversation reconstruction will use transcript timestamps, together with source identity.

The transcription executor does not need to reorder work according to timestamps. Completed segments may be transcribed as they become available.

This avoids unnecessary buffering and latency.

## Observability

Runtime observability must distinguish the two source paths.

Important events and counters should be attributable to the source where relevant, including:

- capture startup and shutdown;
- selected device;
- device loss and recovery;
- capture discontinuities;
- frames captured;
- frames dropped;
- segments emitted;
- transcription submissions;
- transcription rejections.

The exact metric and structured-logging representation is an implementation detail.

## Alternatives considered

### Mix system and microphone audio before processing

Rejected.

Mixing would produce a single audio stream before VAD and transcription.

Although superficially simpler, it would:

- lose reliable source attribution;
- combine overlapping speakers into the same signal;
- couple VAD and segmentation state;
- require synchronization before mixing;
- couple device recovery;
- make microphone echo of system audio more problematic;
- make later conversation reconstruction substantially harder.

Independent processing preserves information that cannot reliably be recovered after mixing.

### Share stateful processing components between sources

Rejected.

Normalization, VAD, and segmentation maintain stream-specific state.

Sharing them would allow one audio source to affect processing decisions for the other and would prevent clean discontinuity isolation.

### Use one transcription executor per source

Rejected initially.

Separate executors could cause multiple Whisper transcriptions to execute concurrently and increase CPU, GPU, and memory pressure.

The service already treats transcription as slower, resource-sensitive work that must be isolated from real-time audio processing.

One shared bounded executor provides a single place to control transcription resource consumption.

The architecture may revisit transcription parallelism later if measurements demonstrate a need and available hardware can support it safely.

### Give each source an independent timeline starting at zero

Rejected.

Independent relative timelines would lose the actual startup offset between sources and make persisted microphone and system-audio transcripts impossible to reliably reconstruct into one chronological conversation.

## Consequences

### Positive

- Both sides of a call can be captured and transcribed.
- System and microphone processing remain isolated.
- Source identity is preserved.
- Existing normalization, VAD, segmentation, and transcription abstractions remain reusable.
- Whisper remains unaware of capture-specific concerns.
- Device recovery can occur independently.
- Transcription resource usage remains centrally bounded.
- Existing real-time overload guarantees remain applicable.
- Conversation timestamps are comparable across sources.
- The design naturally supports additional audio sources in the future without requiring audio mixing.

### Negative

- Two independent real-time paths require additional composition and lifecycle coordination.
- Stateful processing components must be instantiated once per source.
- Transcript persistence requires source information.
- Timestamp handling becomes more explicit because captures must share a conversation timeline.
- Runtime observability must distinguish sources.
- Startup, shutdown, and failure handling become more complex because multiple capture paths share downstream resources.

### Risks

- Different physical audio devices may have clock drift during long-running sessions.
- Microphone input may contain acoustic echo of system audio.
- Combined microphone and system transcription load may saturate the shared transcription queue more frequently.
- One source may disproportionately consume shared transcription capacity.
- Device-specific Windows behavior may require microphone-specific recovery logic.

These risks will be measured and addressed based on real-device testing rather than introducing speculative complexity into the initial design.

## Follow-up work

Implementation following this ADR should proceed in small increments:

1. Introduce the shared conversation timeline abstraction.
2. Introduce source identity at the source-processing/shared-transcription boundary.
3. Refactor transcription-executor lifecycle ownership out of an individual source pipeline.
4. Introduce higher-level orchestration for multiple source pipelines.
5. Update transcript persistence to retain source identity.
6. Define microphone device-selection and recovery behavior.
7. Implement microphone capture.
8. Compose independent microphone normalization, VAD, and segmentation components.
9. Run system and microphone processing concurrently.
10. Add per-source observability.
11. Validate the complete architecture with a real two-person call.

Microphone-specific capture policy, including Windows input-device discovery and default-device behavior, will be decided separately without reopening the multi-source topology established here.