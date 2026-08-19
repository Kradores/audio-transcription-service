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

### Later

* ⬜ Tune VAD and segmentation parameters
* ⬜ Investigate persistence failure/retry requirements
* ⬜ Evaluate additional transcription workers based on measurements
* ⬜ Add transcript querying/inspection capability
* ⬜ Add broader Windows recovery testing
* ⬜ Evaluate packaging/deployment

No additional transcription concurrency should be introduced unless runtime
measurements demonstrate that a single worker cannot satisfy the required
throughput.
