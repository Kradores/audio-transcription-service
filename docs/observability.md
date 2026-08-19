# Observability

## Purpose

The first observability milestone is intentionally diagnostic rather than a
full metrics/telemetry subsystem.

The immediate question is:

> At which processing boundary is live speech being lost?

The runtime path is:

```text
AudioCapture
    ↓
AudioNormalizer
    ↓
Silero VAD
    ↓
SpeechSegmentAssembler
    ↓
Faster-Whisper
    ↓
TranscriptRecorder
    ↓
SQLite
```

Observability must let us compare what crossed each boundary without logging
every 20 ms audio frame.

## Logging strategy

The application uses the standard-library `logging` package as defined by
ADR-017. Logs are emitted at meaningful lifecycle and semantic events rather
than for every processing frame.

Normal runtime logs must not include transcript text. Transcript text is
available at `DEBUG` level for controlled diagnostic runs.

## Current diagnostic events

### Audio capture

The capture boundary logs:

- capture started;
- selected output device, including native channel count and sample rate;
- native capture-frame format;
- Windows audio-device monitor started and stopped;
- Windows default output endpoint changes;
- default-output change signals received by capture;
- recovery started, including the recovery reason;
- capture recovered;
- device becoming inactive;
- dropped-frame events when the bounded transport overflows;
- capture stopped with the total dropped-frame count.

Capture recovery may be triggered either because the current stream becomes
unusable or because Windows reports that the default output endpoint changed.

The latter is important because the old loopback stream may remain active even
though Windows is now routing audio to another endpoint.

Capture discontinuities are surfaced to `SpeechPipeline`, which logs the
processing-state reset.

### Speech pipeline

`SpeechPipeline` maintains a small set of runtime counters:

- `captured_frames` — frames received from `AudioCapture`;
- `processing_frames` — normalized processing frames produced;
- `segments_emitted` — speech segments emitted by the assembler;
- `transcriptions_completed` — transcription calls that completed successfully.

At INFO level, the pipeline logs:

- `SpeechStart` and `SpeechEnd` events with timestamps;
- every emitted speech segment with a pipeline-local sequential ID, start,
  duration, and end timestamp;
- every completed transcription with its segment ID and timestamps;
- final pipeline counters when the pipeline stops.

### Faster-Whisper

The transcriber logs:

- transcription start with segment timestamp and duration;
- inference completion with segment timestamp, duration, inference duration,
  and detected language.

The resulting transcript text is logged only at DEBUG level.

### Transcript recorder

The recorder logs:

- successful persistence with transcript timestamps;
- persistence failures with the exception and transcript timestamps.

A successful recorder call means the repository operation completed
successfully. SQLite-specific SQL/commit logging is not required at this
boundary.

## Diagnostic interpretation

The logs should allow an investigation to follow one piece of speech through
the system:

```text
Capture
  ↓
processing frame count
  ↓
VAD SpeechStart/SpeechEnd
  ↓
SpeechSegment id + timestamp/duration
  ↓
Whisper inference
  ↓
TranscriptRecorder
  ↓
SQLite
```

Interpretation:

- speech absent from VAD events → investigate capture/normalization/VAD;
- VAD event present but no corresponding segment → investigate the assembler;
- segment present but transcription missing/failing → investigate Whisper or
  its input audio;
- transcription completed but persistence missing/failing → investigate the
  recorder/repository boundary.

Capture discontinuities and dropped frames must be considered when comparing
these stages because a discontinuity intentionally resets downstream state
and discards incomplete speech state.

### Device-change interpretation

A timestamp gap around a Windows output-device change does not by itself
indicate capture failure.

Windows may require several seconds to transition between output endpoints.
During that interval there may be no usable default endpoint from which the
application can capture audio.

For recovery diagnostics, distinguish:

```text
Windows device-transition interval
        ↓
default endpoint becomes available
        ↓
capture recovery
        ↓
frame delivery resumes
```
The application's recovery behavior should therefore be evaluated from the
point at which a usable default endpoint becomes available rather than by
assuming that the operating-system device switch is instantaneous.
A successful recovery should be visible as:
```text
default audio output changed
        ↓
capture default output change signaled
        ↓
capture recovery started
        ↓
new capture device selected
        ↓
capture recovered
        ↓
capture discontinuity detected; processing state reset
```

## Deliberately not implemented yet

The diagnostic pass does not introduce:

- Prometheus or another metrics backend;
- OpenTelemetry;
- a metrics abstraction or protocol;
- per-frame logging;
- Silero probability logging;
- audio debug dumps;
- VAD or segmentation parameter changes.

These can be introduced if the diagnostic evidence shows that they are needed.

## Next investigation

Run the application with a known piece of live speech and compare:

```text
speech that was played
vs.
VAD events
vs.
speech segments
vs.
Whisper results
vs.
persisted transcripts
```

Only after identifying the responsible boundary should VAD or segmentation
parameters be changed.


## Transcription execution

The transcription execution boundary must expose enough information to
distinguish real-time audio health from transcription backlog.

The following runtime information should be observable:

- transcription queue capacity;
- transcription queue depth;
- transcription jobs submitted;
- transcription jobs completed;
- transcription jobs failed;
- transcription queue wait duration;
- transcription inference duration.

The existing `Transcriber` inference timing remains useful:

```text
transcription started
    ↓
transcription inference completed
```

The new execution boundary additionally makes queue waiting observable:
```
SpeechSegment emitted
    ↓
transcription job submitted
    ↓
queue wait
    ↓
transcription started
    ↓
inference completed
    ↓
result delivered
```

## Backpressure interpretation
Capture-frame drops indicate that the real-time audio path could not consume
captured audio quickly enough.

Transcription queue growth indicates that speech segments are being produced
faster than the transcription worker can process them.

These are different failure modes and must not be conflated.

A healthy runtime should therefore make it possible to distinguish:
```
capture queue pressure
vs.
transcription queue pressure
vs.
transcription inference latency
```

## Current runtime evidence
The initial sequential implementation was measured with Faster-Whisper
processing approximately 5-second segments in approximately 3.1–3.3 seconds.

With the previous capture queue capacity, the pipeline accumulated 722 dropped
audio frames during a real recording.

Increasing the capture queue to 500 frames, with approximately 10 ms per
capture callback, provided approximately 5 seconds of buffering and resulted
in:
```py
frames_dropped = 0
```

Repeated runs produced the same complete transcript.

This establishes that transcription inference was creating backpressure on
the real-time audio path.

The larger capture queue is therefore considered a diagnostic mitigation, not
the architectural solution.

