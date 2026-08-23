# Roadmap

## 🎯 Goal — First Real Transcript

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


## Milestone — Reliable system-audio transcription [2026-08-19]

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

## 🎯 Current Goal — Reliable Real-Time Conversation Transcription [2026-08-23]

The service can now capture and persist both sides of a real Windows
conversation:

```text
System audio ──────┐
                   │
                   ▼
            SpeechPipeline
                   │
                   ┐
                   │
                   ▼
        shared TranscriptionExecutor
                   │
                   ▼
            Faster-Whisper
                   │
                   ▼
           TranscriptRecorder
                   │
                   ▼
                 SQLite
                   ▲
                   │
                   ┘
            SpeechPipeline
                   ▲
                   │
Microphone ────────┘
```

System and microphone processing are independent up to the shared
transcription execution boundary.

Source identity and a common conversation timeline are preserved through
persistence.

### Current runtime status

Completed:

- ✅ first real persisted system-audio transcript;
- ✅ transcription execution decoupled from real-time processing;
- ✅ bounded non-blocking transcription queue;
- ✅ overload rejection without crashing the service;
- ✅ shared conversation timeline;
- ✅ system-audio and microphone source identity;
- ✅ two independent source-processing pipelines;
- ✅ shared transcription executor;
- ✅ two-sided conversation persistence;
- ✅ Windows default-output recovery;
- ✅ Windows default-microphone recovery;
- ✅ notification-storm debounce / settled-device recovery;
- ✅ real hardware validation through repeated device switching;
- ✅ zero capture-frame drops during recent aggressive recovery test;
- ✅ long-running real two-person conversation test;
- ✅ per-source segmentation observability;
- ✅ transcription queue/backlog observability;
- ✅ queue-wait and transcription-duration statistics;
- ✅ full quality gate: Ruff, mypy, pytest.

### Current measured limitation

A real approximately 30-minute two-person conversation demonstrated sustained
transcription overload.

Observed before the new observability instrumentation:

```text
persisted transcript rows = 421
rejected speech fragments = 162
```

The service remained alive and real-time capture continued, which validates the
runtime overload policy.

However, this rejection level is not acceptable as the long-term transcription
quality target.

The same test also showed unstable automatic language detection in a
conversation that was primarily Romanian with smaller amounts of English,
Spanish, and Russian.

Both issues are now tracked as product/runtime improvements.

---

## Next milestone — Determine the transcription throughput strategy

Before changing transcription concurrency or segmentation behavior, collect
runtime measurements using the newly added observability.

For each realistic 10–30 minute two-sided conversation, collect:

```text
system SpeechPipeline:
    segments_emitted
    segments_rejected
    short_segments
    avg_segment_duration
    max_segment_duration

microphone SpeechPipeline:
    segments_emitted
    segments_rejected
    short_segments
    avg_segment_duration
    max_segment_duration

TranscriptionExecutor:
    submitted
    completed
    rejected
    failed
    queue_high_water_mark
    avg_queue_wait
    max_queue_wait
    avg_transcription_duration
    max_transcription_duration
```

### Decision to make

Use the measurements to choose between:

```text
A. segment aggregation / fewer Whisper jobs

B. additional transcription worker capacity

C. a combination of aggregation and additional workers
```

The decision must account for:

- rejection rate;
- queue latency;
- segment-duration distribution;
- Whisper inference duration;
- CPU/GPU/RAM contention;
- transcript ordering requirements;
- user hardware variability.

Do not increase queue capacity as the primary solution.

A larger queue may temporarily reduce rejection while increasing transcript
latency, but it does not increase transcription throughput.

Do not add multiple Whisper workers solely because the current queue saturates.

Concurrent workers may improve throughput on some hardware but may also cause
CPU/GPU contention and make total throughput worse.

Benchmark before deciding.

---

## Following milestone — Language policy

The current per-segment unrestricted automatic language detection performs
poorly in multilingual conversations where one language dominates.

The first real long-running conversation showed Romanian speech being
frequently detected/transcribed as unrelated languages.

Investigate a configuration-driven language policy supporting use cases such
as:

```text
primary language: Romanian

expected languages:
- Romanian
- English
- Spanish
- Russian
```

The transcription implementation must remain generic and must not hard-code
these specific languages.

Determine whether the eventual policy should support:

```text
automatic language detection
fixed language
preferred/constrained language set
```

This work should follow the immediate throughput investigation so additional
language-detection work does not make an already overloaded transcription
path more expensive without measurement.

---

## Reliability follow-up

Unexpected capture lifecycle failures must eventually propagate to
`SpeechPipeline` / `ConversationPipeline`.

Expected hardware/device failures already recover automatically.

The remaining gap is an unexpected failure of the internal capture lifecycle
task that could otherwise leave one source silently inactive while the
conversation continues.

Address this separately from normal device recovery.

---

## Later investigations

### Duplicate speech across sources

Characterize cases where system playback is also captured by the microphone.

Determine whether the cause is:

- physical speaker-to-microphone echo;
- headset monitoring;
- Bluetooth profile behavior;
- audio-driver routing.

Do not introduce software deduplication until the physical/device behavior is
understood.

### Bluetooth headset profile changes

Using microphone + playback on some Bluetooth headsets may cause Windows to
switch to a bidirectional headset profile with reduced playback quality.

This is currently lower priority than transcription completeness and
reliability.