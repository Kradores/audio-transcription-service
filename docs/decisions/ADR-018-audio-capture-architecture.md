# ADR-018: Audio Capture Architecture

## Status
Accepted

## Context/Reason
We need a reliable, replaceable Windows system-audio capture boundary without coupling the application to a specific native audio library.

## Decision
Use `PyAudioWPatch` behind an application-owned audio-capture abstraction, with device discovery/recovery isolated in the adapter; keep capture representation separate from downstream audio normalization. The remaining API, buffering, lifecycle, and recovery semantics should be finalized before implementation.
Capture produces fixed-duration audio frames rather than speech segments. Semantic buffering is owned by the downstream audio-processing pipeline because speech segmentation is a VAD concern and must not couple the capture implementation to downstream processing.

### Backend
PyAudioWPatch is used as the initial Windows/WASAPI implementation.

### Abstraction
The application depends on an application-owned `AudioCapture` abstraction.

### Boundary
Capture produces timestamped audio frames, not speech segments.

### Capture vs processing format
Capture format is independent from the downstream processing format.

### Buffer ownership
Transport buffering belongs to capture; semantic speech buffering belongs to the downstream audio-processing pipeline.

### Streaming model
The application consumes audio through an asynchronous stream.

### Native callback isolation
PyAudioWPatch callbacks remain internal to the adapter and are not exposed to application consumers.

### Queue
A bounded queue separates the native capture callback from the asynchronous application consumer.

### Overflow
Queue insertion is non-blocking. When capacity is exhausted, frames may be dropped and an observable overflow event is emitted.

### Lifecycle
Capture exposes explicit `start()`, `frames()`, and `stop()` lifecycle semantics.

### Frame size
Capture produces timestamped audio frames in the capture subsystem's configured/native acquisition granularity. The downstream audio-processing pipeline assembles normalized output into exactly 20 ms `ProcessingAudioFrame`s.

### observability
Capture failures and queue overflow must be observable.

### Recovery
Capture remains alive indefinitely when no usable output device is available and retries until recovery or application shutdown.

### core data-flow architecture
- Capture produces frames.
- Capture owns hardware/WASAPI concerns.
- Capture emits native-format `AudioFrame`s.
- A bounded queue decouples the native callback from async consumers.
- Normalization owns processing-format conversion.
- Normalization is stateful.
- SoXR performs streaming resampling.
- Normalization owns output framing.
- VAD receives exactly 20 ms, 16 kHz, mono, float32 frames.
- Device failures/recovery remain inside the capture infrastructure.
