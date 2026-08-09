# ADR-023: VAD and speech buffer semantics

## Decision
| Area                         | Recommendation              |
| ---------------------------- | --------------------------- |
| VAD output                   | Speech start/end events     |
| VAD owns audio buffering     | **No**                      |
| creates speech segments      | `SpeechSegmentAssembler`    |
| Pre-roll                     | **200 ms initial default**  |
| Post-roll                    | **200 ms initial default**  |
| Target segment               | **~3 seconds**              |
| Maximum segment              | **5 seconds**               |
| Natural boundary             | Prefer VAD speech-end       |
| Target reached               | Don't force boundary        |
| Maximum reached              | Force boundary              |
| Long continuous speech       | Multiple segments           |
| Segment overlap              | **No initially**            |
| VAD silence hysteresis       | Required                    |
| Capture recovery gap         | Treat as segment boundary   |
| Shutdown with active segment | Discard                     |
| Segment format               | 16 kHz / mono / float32     |
| Segment timing               | Original monotonic timeline |

The only values I'd consider provisional rather than architectural are the exact `200 ms`, `3 s`, `5 s`, and VAD threshold values. Those should be configuration and validated empirically.

The important architectural decision is the ownership model:
- VAD detects speech. `SpeechSegmentAssembler` creates speech segments.