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