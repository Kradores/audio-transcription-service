# ADR-021: Audio Normalization

## Decision
| Area                | Decision                                         |
| ------------------- | ------------------------------------------------ |
| Resampling          | **Python-SoXR / libsoxr**                        |
| Resampling mode     | **Streaming `ResampleStream`**                   |
| Initial quality     | **HQ**                                           |
| Processing format   | **16 kHz / mono / float32**                      |
| Downmix             | NumPy-based stereo → mono                        |
| Normalizer          | Stateful `AudioNormalizer`                       |
| Resampler lifecycle | One per continuous input format/session          |
| Format changes      | Reset/recreate normalizer/resampler              |
| SciPy               | **Not added solely for resampling**              |
| Output framing      | `AudioNormalizer` owns an output-frame assembler |
| VAD input           | **Exactly 20 ms frames**                         |

The processing side now looks like:
```
AudioFrame
native rate / channels / int16
        │
        ▼
┌───────────────────────────┐
│      AudioNormalizer      │
│                           │
│  int16 → float32          │
│  stereo → mono            │
│  native rate → 16 kHz     │
│                           │
│  streaming resampler      │
│  output-frame assembler   │
└─────────────┬─────────────┘
              │
              ▼
ProcessingAudioFrame
16 kHz / mono / float32
exactly 20 ms
              │
              ▼
             VAD
```