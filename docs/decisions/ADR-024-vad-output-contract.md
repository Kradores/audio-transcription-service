# ADR-024: VAD output contract

## Decision
`SileroVADAdapter` exposes discrete `SpeechStart` / `SpeechEnd` events as its application-level contract. Silero probability/state remains internal to the adapter, with diagnostic information available through observability if needed. The adapter processes `ProcessingAudioFrames` and produces VAD results in deterministic frame order.

| Area               | Decision                                                            |
| ------------------ | ------------------------------------------------------------------- |
| VAD engine         | **Silero VAD**                                                      |
| Integration        | Dedicated `SileroVADAdapter`                                        |
| Public input       | 20 ms `ProcessingAudioFrame`                                        |
| Silero window      | **512 samples @ 16 kHz (~32 ms)**                                   |
| Window assembly    | Owned by VAD adapter                                                |
| Model lifecycle    | Load once, keep alive                                               |
| VAD state          | Stateful across frames                                              |
| Reset              | Explicit reset of model + adapter state                             |
| Threshold          | Start at **0.5**, configurable                                      |
| Negative threshold | Use Silero hysteresis initially                                     |
| Minimum speech     | Start at **250 ms**, configurable                                   |
| Minimum silence    | Start around **200 ms**, tune experimentally                        |
| Silero padding     | Disabled initially                                                  |
| Application padding| **200 ms pre + 200 ms post**                                        |
| Padding ownership  | `SpeechSegmentAssembler` initially                                  |
| Segment ownership  | `SpeechSegmentAssembler`                                            |
| Batch API          | Don't use `get_speech_timestamps()` for streaming                   |
| Runtime            | Start with one runtime; benchmark PyTorch vs ONNX later             |
| Testing            | Fake engine + deterministic fixtures + real model integration tests |
| Timestamp source   | Our monotonic timeline                                              |
| Experiment         | Compare assembler-owned padding with Silero-native padding          |


### VAD architecture
```
                    ProcessingAudioFrame
                    16k / mono / float32
                           20 ms
                              │
                              ▼
                    ┌──────────────────┐
                    │ SileroVADAdapter │
                    │                  │
                    │ 20ms → 512 samp  │
                    │ window assembler │
                    │                  │
                    │ Silero state     │
                    │ threshold        │
                    │ hysteresis       │
                    └────────┬─────────┘
                             ▼
                      ┌──────────────┐
                      │              │
                      ▼              ▼
                  VAD event       original frame
                      │              │
                      └──────┬───────┘
                             ▼
                 SpeechSegmentAssembler
                             │
                             ├── pre-roll
                             ├── speech frames
                             ├── post-roll
                             ├── target duration
                             └── maximum duration
                             │
                             ▼
                       SpeechSegment
                             │
                             ▼
                       Whisper
```

### Experiment (needs testing before decision)
Silero-native padding is disabled in the initial implementation so that padding ownership is unambiguous. During integration testing, we may enable/evaluate Silero's native padding and compare it against the assembler-owned approach. This is an experiment, not a change to the current architecture.