# Roadmap

## 🎯 Current Goal — First Real Transcript

The current milestone is to run the complete application on Windows and
produce the first real persisted transcript.

### Definition of success

```text
Windows system audio
        ↓
WASAPI loopback capture
        ↓
Audio normalization
        ↓
Silero VAD
        ↓
Speech segment assembly
        ↓
Faster-Whisper transcription
        ↓
TranscriptionResult
        ↓
TranscriptRecorder
        ↓
SQLite
```

Success means:

1. `uv run python -m app` starts and remains running.
2. The application captures real system audio.
3. Speech is detected.
4. A speech segment is created.
5. Faster-Whisper produces a `TranscriptionResult`.
6. The result is delivered to `TranscriptRecorder`.
7. SQLite persists the result.
8. The persisted transcript can be verified in the database.
9. The application shuts down cleanly.

---

## Completed foundation

### Configuration and bootstrap

* ✅ Project structure
* ✅ Python tooling
* ✅ Typed configuration
* ✅ Configuration loader
* ✅ Production/example configuration
* ✅ Logging
* ✅ Application lifecycle foundation
* ✅ Composition root
* ✅ Entry points
* ✅ Startup integration tests

### Audio capture

* ✅ PyAudioWPatch / WASAPI loopback
* ✅ Application-owned `AudioCapture`
* ✅ Bounded asynchronous transport
* ✅ Frame ownership and timestamps
* ✅ Device recovery
* ✅ Capture discontinuity notification
* ✅ Discontinuity propagation to the speech pipeline

### Audio processing

* ✅ Audio normalization
* ✅ Streaming resampling
* ✅ Downmixing
* ✅ Fixed 20 ms processing frames
* ✅ Normalizer reset semantics

### Speech detection and segmentation

* ✅ Silero VAD boundary
* ✅ VAD state/reset semantics
* ✅ SpeechStart / SpeechEnd contract
* ✅ SpeechSegmentAssembler
* ✅ Pre-roll/post-roll
* ✅ Maximum-duration splitting
* ✅ Discontinuity reset semantics

### Transcription

* ✅ `Transcriber` contract
* ✅ `TranscriptionResult`
* ✅ Faster-Whisper adapter
* ✅ Sequential pipeline transcription
* ✅ Worker-thread execution for blocking inference
* ✅ Result delivery boundary

### Persistence

* ✅ `TranscriptRecorder`
* ✅ `TranscriptRepository`
* ✅ SQLite repository
* ✅ Initial schema
* ✅ Append-only persistence
* ✅ Transaction/commit behavior
* ✅ SQLite configuration and startup wiring
* ✅ No migration framework yet

### Verification

* ✅ Unit test suite
* ✅ Integration test foundation
* ✅ Ruff
* ✅ Ruff format
* ✅ MyPy
* ✅ 218 tests passing

---

# Path to the first transcript

## 1. Complete production composition

* ✅ Verify the complete production object graph
* ✅ Wire `TranscriptRecorder` into `SpeechPipeline` result delivery
* ✅ Verify SQLite repository/database ownership
* ✅ Add/adjust composition integration coverage

## 2. Verify real ML components

* ✅ Real Silero integration test
* ✅ Real Faster-Whisper integration test
* ✅ Verify Python 3.14 runtime compatibility
* ✅ Resolve any model-loading/runtime compatibility issues discovered

## 3. Verify real WASAPI capture

* ✅ Windows integration test with a real default output device
* ✅ Verify loopback frame acquisition
* ✅ Verify capture format and timestamps
* ✅ Verify real startup/shutdown behavior

## 4. Complete application runtime lifecycle

* ✅ Keep the application alive after startup
* ✅ Add graceful shutdown handling
* ✅ Ensure pipeline and database resources are released
* ✅ Update startup integration tests for long-running lifecycle semantics

## 5. First end-to-end transcript

* ✅ Run the application against real system audio
* ✅ Produce a real `SpeechSegment`
* ✅ Produce a real `TranscriptionResult`
* ✅ Persist the result to SQLite
* ✅ Verify the persisted transcript
* ✅ Verify clean shutdown

---

## After the first transcript

### Runtime validation

* ✅ Measure capture/transcription throughput
* ✅ Measure transcription latency
* ✅ Inspect queue pressure and dropped frames
* ✅ Improve runtime observability
* ✅ Identify transcription-induced capture backpressure

### Next architectural increment

* ✅ Decouple real-time audio processing from transcription execution
* ✅ Introduce bounded transcription work queue
* ✅ Introduce single transcription worker
* ✅ Preserve chronological transcription result delivery
* ✅ Define transcription queue shutdown semantics
* ✅ Define transcription queue overflow behavior
* ✅ Add unit and integration coverage for transcription scheduling
* ✅ Re-run real end-to-end workload and verify zero capture-frame loss
* ✅ Measure transcription queue pressure and end-to-end latency


## Current milestone — Reliable system-audio transcription [2026-08-19]

Status: ✅ Complete

The service can now run continuously on Windows and produce persisted
transcripts from live system audio.

Completed:

- Windows WASAPI loopback capture;
- streaming normalization to 16 kHz mono float32;
- Silero VAD;
- speech-segment assembly with configurable pre-roll, post-roll,
  target duration, and maximum duration;
- Faster-Whisper transcription;
- SQLite transcript persistence;
- diagnostic observability across the processing pipeline;
- transcription execution decoupled from real-time audio processing;
- bounded transcription queue with non-fatal overload handling;
- automatic recovery when the active Windows output device disappears;
- automatic following of Windows default-output device changes;
- downstream processing-state reset across capture discontinuities;
- real-device validation of output-device recovery;
- real end-to-end transcription validated with live system audio;
- segmentation tuned against real speech so that segments normally end
  at natural speech boundaries rather than the maximum-duration limit.

The current system is therefore capable of reliably transcribing the
system-audio side of a conversation.

---

## Next milestone — Complete conversation capture

### Goal

Capture and transcribe both sides of a real call:

```text
Remote participant
        ↓
Windows system audio / WASAPI loopback
        ↓
transcription

Local participant
        ↓
microphone
        ↓
transcription
```
System-audio capture alone is insufficient for the intended use case because
the local user's microphone speech is normally not present in the loopback
stream.
The next milestone is therefore to add microphone capture while preserving
the existing real-time, recovery, segmentation, transcription, and
persistence guarantees.

**Step 1 — Define multi-source audio architecture**
Before implementation, decide:
- how system-audio and microphone capture coexist;
- whether each source owns an independent normalization/VAD/segmentation path;
- how audio-source identity is represented;
- how both sources share transcription execution;
- how timestamps from both sources relate to one common conversation timeline;
- how source identity reaches persisted transcript records;
- how microphone-device selection and recovery behave.

Target conceptual flow:
```
System Audio Capture ──→ processing ──→ segments ──┐
                                                   │
                                                   ▼
                                         Transcription Executor
                                                   │
                                                   ▼
                                           Transcript Storage
                                                   ▲
                                                   │
Microphone Capture ───→ processing ──→ segments ───┘
```
No implementation should begin until ownership and lifecycle semantics for
the two capture sources are clear.

**Step 2 — Introduce microphone capture**
Implement microphone/input-device capture behind the existing audio
abstractions where appropriate.
Requirements:
- continuous native microphone capture;
- bounded, non-blocking frame transport;
- timestamps compatible with the conversation timeline;
- clean start/stop lifecycle;
- device-loss recovery;
- observable device selection and recovery;
- no microphone-specific behavior leaking into VAD or transcription.

**Step 3 — Process microphone speech**
Feed microphone audio through the established processing stages:
```
microphone
    ↓
normalization
    ↓
VAD
    ↓
speech segmentation
    ↓
transcription executor
```

**Step 4 — Preserve transcript source identity**
A persisted transcript must identify where the speech originated.
At minimum distinguish:
- system audio;
- microphone.
This prepares the transcript for later reconstruction of an actual
conversation rather than an undifferentiated stream of text.

**Step 5 — Integrate both sources concurrently**
Run system-audio and microphone capture simultaneously.
Verify:
- neither source blocks the other;
- transcription remains outside the real-time processing path;
- overload remains bounded and non-fatal;
- capture recovery for one source does not unnecessarily reset the other;
- timestamps remain comparable;
- shutdown drains accepted transcription work cleanly.

**Step 6 — Real-call validation**
Run an actual call with speech from both participants.
Verify that the persisted transcript contains:
- remote speech from system audio;
- local speech from the microphone;
- correct chronological timestamps;
- correct source identity;
- no systematic missing speech;
- natural segmentation;
- acceptable transcription latency;
- stable long-running behavior.

**Milestone completion criteria**
The milestone is complete when a real two-person call can be captured and
persisted as a chronological transcript containing both the remote and local
sides of the conversation.