# High-Level Architecture

```
                         APPLICATION
──────────────────────────────────────────────────────────

                    Real-time audio path

WASAPI Loopback
      ↓
AudioCapture
      ↓
AudioNormalizer
      ↓
VAD
      ↓
SpeechSegmentAssembler
      ↓
SpeechSegment
      ↓
┌───────────────────────────────┐
│ Transcription work queue      │
│ bounded, application-owned    │
└───────────────┬───────────────┘
                ↓
       Transcription worker
                ↓
           Transcriber
                ↓
      TranscriptionResult
                ↓
      TranscriptResultHandler
                ↓
       TranscriptRecorder
                ↓
      TranscriptRepository
                ↓
──────────────────────────────────────────
              INFRASTRUCTURE
             SQLite
```

# Project Structure
```
audio-transcription-service/
│
├── app/
│   ├── api/
│   │   ├── __init__.py
│   │   ├── health.py
│   │   └── status.py
│   │
│   ├── audio/
│   ├── transcription/
│   ├── vad/
│   ├── storage/
│   │
│   ├── core/
│   │   ├── __init__.py
│   │   ├── config.py
│   │   ├── logging.py
│   │   └── lifecycle.py
│   │
│   ├── models/
│   ├── services/
│   ├── utils/
│   │
│   ├── main.py
│   └── __init__.py
│
├── config/
│   └── config.yaml
│
├── docs/
│   ├── architecture.md
│   ├── roadmap.md
│   ├── testing.md
│   ├── observability.md
|   ├── engineering-principles.md
│   ├── development.md
│   └── decisions/
│
├── scripts/
│
├── tests/
│   ├── unit/
│   ├── integration/
│   └── resources/
│
├── .gitignore
├── pyproject.toml
├── README.md
└── LICENSE
```

## Audio architecture (partial)
```
                         Application
                              │
                              ▼
                     ┌─────────────────┐
                     │  AudioCapture   │
                     │   abstraction   │
                     └────────┬────────┘
                              │
                              ▼
                  ┌──────────────────────┐
                  │ WASAPIAudioCapture   │
                  │      adapter         │
                  └──────────┬───────────┘
                             │
                             ▼
                     PyAudioWPatch
                             │
                             ▼
                       Windows WASAPI
                             │
                             ▼
                    Default output mix
                             │
                             ▼
                    ┌─────────────────┐
                    │ Audio frames    │
                    │ + timestamps    │
                    └────────┬────────┘
                             │
                             ▼
                       Audio Pipeline
                             │
                             ▼
                      VAD → Whisper
```


## Current capture decisions
| Area                        | Decision                                     |
| --------------------------- | -------------------------------------------- |
| Backend                     | **PyAudioWPatch**                            |
| Boundary                    | Application-owned `AudioCapture` abstraction |
| Capture output              | Audio frames, **not speech segments**        |
| Logical frame size          | **20 ms**                                    |
| Frame samples               | `numpy.ndarray[int16]`                       |
| Array shape                 | `(samples, channels)`                        |
| Ownership                   | `AudioFrame` owns its sample memory          |
| Timestamp                   | Monotonic seconds since capture start        |
| Duration                    | Explicit field                               |
| Capture format              | Native/device PCM representation             |
| Processing format           | Separate downstream concern                  |
| Semantic buffering          | Audio-processing pipeline                    |
| Native callback             | Internal to adapter                          |
| Application streaming       | Async iterator                               |
| Internal transport          | Bounded thread-safe queue                    |
| Queue producer              | Non-blocking                                 |
| Queue overflow              | Drop + observable event                      |
| Device                      | Windows default output device                |
| Device selection            | Internal to capture adapter                  |
| Device changes              | Automatically follow new default             |
| Device loss                 | Automatically recover                        |
| Recovery                    | **Indefinite while application runs**        |
| Retry                       | Exponential backoff, capped around 5s        |
| Recovery consumer           | `frames()` remains alive                     |
| Timestamp after recovery    | Same monotonic timeline                      |
| Device-change marker        | Not part of `AudioFrame`                     |
| Device format changes       | Allowed; normalize downstream                |
| Fatal initialization errors | Fail startup                                 |


## Resampling architecture (partial)
```
AudioCapture
    │
    ▼
AudioFrame
int16 / native channels
    │
    ▼
AudioNormalizer
    │
    ├── convert to float32
    │
    ├── downmix to mono
    │
    └── resample to 16 kHz
    │
    ▼
ProcessingAudioFrame
    │
    ├── 16 kHz
    ├── mono
    └── float32
    │
    ▼
VAD
```
```
AudioNormalizer
       │
       │ maintains resampling state
       ▼
Frame 1 ──┐
Frame 2 ──┤
Frame 3 ──┤──► normalized frames
Frame 4 ──┤
   ...    │
```
The normalizer should therefore be treated as a streaming component, not a stateless function.

This is another reason why `AudioNormalizer` deserves its own interface.


## resulting audio ownership matrix
| Responsibility                      | Owner                    |
| ----------------------------------- | ------------------------ |
| WASAPI                              | `AudioCapture` adapter   |
| PyAudioWPatch                       | `AudioCapture` adapter   |
| Device selection                    | `AudioCapture` adapter   |
| Device recovery                     | `AudioCapture` adapter   |
| Native callback                     | `AudioCapture` adapter   |
| Native frame acquisition            | `AudioCapture` adapter   |
| Transport queue                     | Capture subsystem        |
| Capture lifecycle                   | Capture subsystem        |
| Capture timestamps                  | Capture subsystem        |
| Format conversion                   | `AudioNormalizer`        |
| Resampling                          | `AudioNormalizer`        |
| Downmixing                          | `AudioNormalizer`        |
| **20 ms processing-frame assembly** | **`AudioNormalizer`**    |
| Silero model                        | `SileroVADAdapter`       |
| VAD state                           | `SileroVADAdapter`       |
| Speech detection                    | `SileroVADAdapter`       |
| `SpeechStart` / `SpeechEnd`         | `SileroVADAdapter`       |
| Pre-roll                            | `SpeechSegmentAssembler` |
| Post-roll                           | `SpeechSegmentAssembler` |
| Semantic buffering                  | `SpeechSegmentAssembler` |
| Segment boundaries                  | `SpeechSegmentAssembler` |
| Maximum-duration splitting          | `SpeechSegmentAssembler` |
| `SpeechSegment` creation            | `SpeechSegmentAssembler` |
| Transcription                       | Whisper pipeline         |


## key ownership statement
`SpeechPipeline` remains storage-agnostic. It delivers completed `TranscriptionResult` values through its result handler. `TranscriptRecorder` owns the application-level transition into persistence, while `TranscriptRepository` abstracts persistence mechanics.


## discontinuity path
```
AudioCapture
    │
    │ discontinuity callback
    ▼
SpeechPipeline
    │
    ├── AudioNormalizer.reset()
    ├── AudioVad.reset()
    └── SpeechSegmentAssembler.reset()
```


## Real-Time Audio and Transcription Execution Boundary

The real-time audio-processing path must not wait for speech-to-text
inference.

`AudioCapture`, normalization, VAD, and speech-segment assembly operate as a
continuous processing path. When a `SpeechSegment` is emitted, the segment is
submitted to the transcription execution boundary.

Transcription execution is handled independently from real-time audio
processing through a bounded transcription work queue and a dedicated
transcription worker.

The `Transcriber` contract remains synchronous. The worker is responsible for
executing that synchronous contract without blocking the real-time processing
path.

The initial implementation uses a single transcription worker. Additional
workers are not introduced unless runtime measurements demonstrate that a
single worker cannot maintain the required throughput.

The capture transport remains responsible for buffering native audio frames.
It is not used as the primary buffering mechanism for transcription latency.


## Windows default-output recovery

The Windows `PyAudioCapture` implementation follows the current Windows
default output device automatically.

Default render-device changes are detected through a replaceable
`AudioDeviceMonitor`. The production implementation uses Windows Core Audio
endpoint notifications through `pycaw`.

```text
Windows default output changes
        │
        ▼
WindowsAudioDeviceMonitor
        │
        │ lightweight notification
        ▼
PyAudioCapture
        │
        ├── close old stream
        ├── terminate old PyAudio instance
        ├── signal capture discontinuity
        ├── create fresh PyAudio instance
        ├── rediscover default WASAPI loopback
        └── open new stream
        │
        ▼
frame delivery resumes
```

`PyAudioCapture` remains the owner of native audio-device discovery, stream
lifecycle, and recovery. The device monitor only reports that the Windows
default output changed.
PyAudio device indexes are transient and are not treated as persistent device
identities.
If Windows temporarily has no usable default output endpoint, capture remains
alive and retries according to the existing recovery policy.
Recovery does not guarantee gapless audio across an output-device change.
Windows may itself take several seconds to transition between endpoints.
Audio unavailable while Windows is performing that transition cannot be
captured. Once a usable default endpoint becomes available, capture follows
it automatically and processing resumes on the existing monotonic timeline.
A successful recovery creates a capture discontinuity. Before recovered audio
is processed, SpeechPipeline resets the normalizer, VAD, and speech segment
assembler so that state from the previous capture continuity domain cannot
cross into the new one.


## Multi-source capture architecture

The service has two independent real-time source-processing paths:

```text
              shared conversation timeline
                         │
             ┌───────────┴───────────┐
             │                       │
             ▼                       ▼
      system_audio               microphone
             │                       │
        AudioCapture              AudioCapture
             │                       │
      AudioNormalizer           AudioNormalizer
             │                       │
          AudioVad                 AudioVad
             │                       │
 SpeechSegmentAssembler    SpeechSegmentAssembler
             │                       │
TranscriptionSegmentAggregator  TranscriptionSegmentAggregator
             │                       │
             └───────────┬───────────┘
                         ▼
             shared TranscriptionExecutor
                    bounded queue
                         │
                  worker_count = 2
                    ┌────┴────┐
                    ▼         ▼
                 worker 1  worker 2
                    │         │
                    └────┬────┘
                         ▼
               shared Whisper model
                         │
                  sourced results
                         │
                TranscriptRecorder
                         │
               TranscriptRepository
                         │
                       SQLite
```

Stateful real-time components remain independent per source.

Source identity is attached when source-specific speech crosses into the shared
transcription execution boundary.

Both captures use one shared monotonic conversation timeline.

## Windows native capture lifecycle

System-audio and microphone capture normally own independent native sessions.

Ordinary source failures therefore remain isolated:

```text
system stream unavailable
        ↓
system-local recovery

microphone stream unavailable
        ↓
microphone-local recovery
```

Windows default-device changes have a different lifecycle requirement.

Real-device testing demonstrated that PortAudio device/default enumeration is
effectively process-wide while multiple PyAudio instances exist.

The composition root therefore provides one shared
`PortAudioRefreshCoordinator` to both capture implementations.

```text
eRender/eConsole change ──────┐
                              │
                              ▼
                    PortAudioRefreshCoordinator
                              ▲
                              │
eCapture/eConsole change ─────┘
                              │
                              ▼
                   close BOTH native streams
                              │
                   terminate BOTH PyAudio
                              │
                    wait for notifications
                         to settle
                              │
                 ┌────────────┴────────────┐
                 ▼                         ▼
           fresh system PyAudio      fresh microphone PyAudio
                 │                         │
      current default loopback     current WASAPI default input
                 │                         │
                 └────────────┬────────────┘
                              ▼
                         capture resumes
```

The coordinator owns only this process-wide native refresh boundary.

It does not own:

- concrete device selection;
- capture queues;
- audio processing;
- VAD;
- segmentation;
- transcription;
- normal source-local recovery.

During coordinated refresh, source-local native reopening is suspended so
PortAudio remains fully terminated until the settle phase is complete.

Both processing paths receive a discontinuity because both native sessions are
refreshed.

The shared conversation timeline is not reset.