# Roadmap

## ✅ Completed milestone — Complete two-sided conversation transcription

The service now supports a complete local two-sided conversation pipeline:

```text
System AudioCapture ──→ source-local processing ──→ aggregator ──┐
                                                                │
                                                                ▼
                                                     shared bounded
                                                  TranscriptionExecutor
                                                      worker_count=2
                                                                │
                                                                ▼
                                                         Faster-Whisper
                                                                │
                                                                ▼
                                                          persistence

Microphone AudioCapture → source-local processing → aggregator ──┘
```

The milestone includes:

- Windows system-audio capture;
- Windows microphone capture;
- independent source-local normalization;
- independent VAD and speech segmentation;
- shared monotonic conversation timeline;
- source-preserving transcription and persistence;
- automatic default-output recovery;
- automatic default-microphone recovery;
- per-source transcription-segment aggregation;
- bounded non-blocking transcription execution;
- runtime overload rejection without crashing the service;
- concurrent Faster-Whisper execution;
- multi-worker lifecycle supervision;
- graceful draining of accepted transcription work;
- application-owned rotating file logging;
- queue, aggregation, capture, and concurrency observability.

### ADR-042 concurrency validation

Concurrent transcription execution has been implemented and validated.

Real-conversation benchmarks produced approximately:

```text
Workers    Rejection    Avg queue wait    Avg inference
--------------------------------------------------------
1          18.36%       28.263 s          4.207 s
2           9.52%       17.676 s          6.740 s
3           0.00%       10.779 s          8.130 s
```

Incoming transcription workload was similar across the three measured
conversations at approximately 18 jobs per minute.

All benchmark runs retained:

```text
capture frames dropped = 0
transcription failures = 0
```

Three workers delivered the highest measured transcription throughput but
kept CPU utilization above approximately 90% during intensive conversation.

The selected default is therefore:

```yaml
transcription:
  worker_count: 2
```

Two workers provide the preferred balance between transcript completeness,
queue latency, and leaving compute capacity available to the call application
and other workloads running on the user's machine.

`worker_count` remains configurable for machines or workloads requiring a
different resource/throughput trade-off.

ADR-042 is considered implemented and runtime validated.

---

## 🎯 Current milestone — Conversation quality and operational hardening

The core capture-to-persistence architecture is now functional.

The next milestone is to improve the quality and operational reliability of
real long-running conversations without destabilizing the validated execution
architecture.

### Current priorities

1. **Long-running stability**
   - continue real 15–30+ minute conversation runs;
   - verify capture remains drop-free;
   - verify executor lifecycle remains clean;
   - watch for resource degradation over time.

2. **Transcription overload visibility**
   - continue using executor rejection and queue-wait statistics as the
     authoritative transcription-capacity signals;
   - preserve reject-newest bounded overload behavior;
   - avoid increasing queue capacity merely to hide sustained throughput
     deficits.

3. **Language behavior**
   - investigate multilingual and short-fragment language detection separately
     from worker concurrency;
   - do not mix language-policy changes into concurrency benchmarking.

4. **Source quality**
   - evaluate source-specific VAD/segmentation tuning only from measured
     conversation evidence;
   - keep system-audio and microphone processing independently configurable
     where justified by evidence.

5. **Resource behavior**
   - retain two workers as the default;
   - treat higher worker counts as explicit machine-specific tuning;
   - avoid automatic worker scaling until there is evidence that it can be
     done reliably.

### Definition of success

The next milestone succeeds when normal real conversations can run for
extended periods while maintaining:

```text
capture-frame drops = 0
application remains responsive
graceful shutdown remains correct
accepted transcription work drains correctly
transcription overload remains observable and bounded
CPU/resource usage remains acceptable for normal desktop use
```

Transcript-quality improvements must not compromise these runtime guarantees.


## As of 2026-08-29 — reliable multi-source Windows capture

### Completed

✅ Two independent capture paths:

```text
system_audio
microphone
```

✅ Shared monotonic conversation timeline

✅ Source-specific normalization, VAD, segmentation, and transcription
aggregation

✅ Shared bounded transcription executor

✅ Concurrent Faster-Whisper execution

✅ `worker_count=2` selected as the balanced default after real-call
benchmarking

✅ Source-tagged SQLite persistence

✅ Windows default render monitoring:

```text
eRender / eConsole
```

✅ Windows default microphone monitoring:

```text
eCapture / eConsole
```

✅ ADR-043 — process-wide PortAudio refresh

A controlled two-PyAudio experiment demonstrated that recreating only one
PyAudio instance can retain stale default-device enumeration while another
instance remains alive.

Default-device changes now coordinate:

```text
all streams closed
        ↓
all PyAudio sessions terminated
        ↓
notification burst settles
        ↓
fresh source-owned sessions created
        ↓
current defaults rediscovered
```

✅ Duplicate Core Audio notification bursts coalesced into one refresh

✅ Source-local native recovery suspended during coordinated refresh

✅ Settings-based output switching validated in both directions

✅ Settings-based microphone switching validated in both directions

✅ Physical disconnect/reconnect validated

✅ Startup with microphone unavailable validated

✅ Later microphone availability/recovery validated

✅ Recovery backoff interrupted immediately by a default-device notification

✅ Both processing paths receive discontinuity reset after coordinated refresh

✅ Capture timeline preserved through recovery

✅ Capture transport remained healthy with:

```text
frames_dropped=0
```

✅ Graceful shutdown validated after repeated native refreshes

### Quality gate

```text
pytest:
402 passed

mypy:
Success: no issues found in 103 source files

ruff:
All checks passed
```

### Current architecture milestone

The complete two-sided Windows capture foundation is now operational:

```text
system audio ─┐
              ├─ independent real-time processing
microphone ───┘
              ↓
per-source aggregation
              ↓
shared bounded concurrent transcription
              ↓
source-tagged persistence
```

Native Windows default-device recovery is now reliable with both audio sources
active.

ADR-043 is implemented and real-device validated.