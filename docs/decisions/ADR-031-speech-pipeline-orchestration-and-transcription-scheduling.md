# ADR-031: Speech Pipeline Orchestration and Transcription Scheduling

## Status

Accepted

## Context

The audio processing components now provide the complete processing chain:

AudioCapture
    ↓
AudioNormalizer
    ↓
AudioVad
    ↓
SpeechSegmentAssembler
    ↓
Transcriber

Each component owns a distinct responsibility:

- AudioCapture owns capture, transport, timestamps, recovery, and capture lifecycle.
- AudioNormalizer owns format conversion, resampling, and exact 20 ms framing.
- AudioVad owns speech-state detection.
- SpeechSegmentAssembler owns semantic speech buffering and SpeechSegment creation.
- Transcriber owns speech-to-text conversion.

The application needs a component that orchestrates these components without
moving their responsibilities into a single implementation.

The Transcriber contract is synchronous, while the audio pipeline is
asynchronous. Faster-Whisper inference can therefore block the event loop if
called directly from asynchronous pipeline code.

The initial implementation does not yet have measured evidence that
concurrent transcription or a dedicated transcription queue is required.

## Decision

### 1. Application-owned SpeechPipeline

The application will introduce a `SpeechPipeline` component responsible for
orchestrating:

- `AudioCapture`;
- `AudioNormalizer`;
- `AudioVad`;
- `SpeechSegmentAssembler`;
- `Transcriber`.

The pipeline does not own the internal behavior of those components.

### 2. Sequential processing

The pipeline processes the stream sequentially.

For each captured frame:

1. normalize the frame;
2. process every emitted `ProcessingAudioFrame`;
3. run VAD;
4. pass the frame and VAD events to the assembler;
5. transcribe every emitted `SpeechSegment`;
6. publish every resulting `TranscriptionResult`.

Only one frame-processing operation is active at a time.

Only one transcription operation is active at a time.

Transcription results therefore preserve input segment order.

### 3. Synchronous Transcriber execution

`Transcriber.transcribe()` remains synchronous.

The pipeline executes the synchronous call using:

`asyncio.to_thread(...)`

This prevents model inference from blocking the asyncio event loop while
retaining single-flight sequential processing.

The pipeline does not introduce concurrent transcription workers.

### 4. Backpressure

The initial pipeline does not introduce an additional processing or
transcription queue.

The existing bounded capture transport remains the initial backpressure
boundary.

If downstream processing cannot keep up, the existing capture transport
retains its established overflow behavior.

A dedicated processing/transcription queue may be introduced later if
measurement demonstrates that it is required.

### 5. Result delivery

The pipeline receives a result callback during construction.

The callback is responsible only for receiving completed
`TranscriptionResult` values.

Persistence, API delivery, or other result handling remains outside the
pipeline.

### 6. Lifecycle

The pipeline exposes explicit asynchronous:

- `start()`
- `stop()`

`start()` starts capture and launches the processing task.

`frames()` does not implicitly start capture.

`stop()` is idempotent.

Calling `stop()` before `start()` is harmless.

The pipeline has no initial restart API.

### 7. Shutdown

Shutdown follows the existing application lifecycle decision:

1. stop capture;
2. terminate/cancel downstream processing;
3. discard incomplete speech-segmentation state;
4. release pipeline resources.

`SpeechSegmentAssembler.reset()` is used to discard incomplete segments.

No synthetic `SpeechEnd` is generated during shutdown.

No incomplete `SpeechSegment` is transcribed.

### 8. Normalizer completion

When the capture stream ends normally, the pipeline calls
`AudioNormalizer.flush()`.

Any complete processing frames emitted by the normalizer are processed through
the same VAD and assembler path.

Incomplete normalizer audio remains discarded according to the normalizer
contract.

### 9. Capture recovery

Capture recovery remains entirely owned by `AudioCapture`.

The pipeline does not restart or recreate the capture component when the
capture implementation temporarily loses its device.

The pipeline continues consuming the capture stream.

### 10. Error handling

Unexpected exceptions from normalization, VAD, segment assembly, or
transcription terminate the pipeline processing task.

The pipeline does not silently continue with potentially inconsistent
state.

The capture resource is stopped when pipeline processing fails.

No automatic pipeline restart is introduced.

### 11. Cancellation

Pipeline cancellation must not create additional concurrent transcription
operations.

The pipeline may cancel its asyncio processing task during shutdown.

The synchronous transcription operation is executed through
`asyncio.to_thread()`. Cancellation of the asyncio task does not forcibly
terminate Python code already executing in the worker thread.

The initial implementation therefore does not promise interruption of an
in-progress model inference operation.

## Consequences

### Positive

- The pipeline remains small and deterministic.
- Processing order is explicit.
- Transcription ordering is preserved.
- Whisper inference does not block the asyncio event loop.
- No unnecessary worker/queue infrastructure is introduced.
- Existing capture backpressure remains the single buffering boundary.
- Component responsibilities remain separated.
- The pipeline can later evolve toward concurrent processing based on
  measured requirements.

### Negative

- Slow transcription can cause downstream processing to fall behind.
- Capture buffering may eventually overflow under sustained transcription
  load.
- A synchronous transcription operation cannot be forcibly interrupted once
  running in a worker thread.
- Throughput may be insufficient for some workloads.

These limitations are intentional for the initial implementation and should
be addressed only after measurement demonstrates the need.

## Alternatives Considered

### Direct synchronous transcription on the event loop

Rejected.

Faster-Whisper inference can block the event loop and interfere with
asynchronous capture consumption and lifecycle handling.

### Concurrent transcription workers

Rejected initially.

There is no measured requirement for concurrent inference yet, and adding
workers would require explicit ordering, queue capacity, memory, shutdown,
and failure semantics.

### Dedicated transcription queue

Rejected initially.

The existing capture transport already provides bounded buffering.
Introducing another queue before measuring the system would add complexity
without demonstrated benefit.

### Make Transcriber asynchronous

Rejected.

The application-owned transcription contract is intentionally synchronous.
Scheduling model execution belongs to the pipeline.

### Automatic pipeline restart

Rejected.

Unexpected processing failures should be visible rather than silently
restarted. Capture-specific recovery remains owned by `AudioCapture`.

## Related Decisions

- ADR-005: Architectural Boundaries
- ADR-016: Application Composition Root
- ADR-018: Audio Capture Architecture
- ADR-022: Shutdown and Lifecycle
- ADR-023: VAD and Speech Buffer Semantics
- ADR-024: VAD Output Contract
- ADR-026: Audio Frame Transport Threading and Asynchronous Consumption
- ADR-028: Voice Activity Detection Architecture and Silero Boundary
- ADR-029: Speech Segment Assembler Contract and State Machine
- ADR-030: Transcription Boundary and Faster-Whisper Adapter