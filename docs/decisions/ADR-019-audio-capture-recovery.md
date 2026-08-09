# ADR-019: Audio Capture Recovery

## Decision
| Decision                             | Recommendation                       |
| ------------------------------------ | ------------------------------------ |
| Device policy                        | Windows default output device        |
| Device selection                     | Internal to capture adapter          |
| Device changes                       | Automatically follow new default     |
| Timestamp after recovery             | Continue same monotonic timeline     |
| Device-change marker in `AudioFrame` | No                                   |
| Temporary device loss                | Recover automatically                |
| Recovery duration                    | Indefinite while application runs    |
| Retry strategy                       | Exponential backoff, capped at approximately 5 seconds   |
| Consumer during recovery             | Remains alive; no frames temporarily |
| Fatal initialization errors          | Fail startup                         |
| No output device                     | Enter recovery rather than terminate |
| Device format changes                | Allowed; processing layer normalizes |
| Session abstraction                  | Keep internal unless needed          |

### device recovery model
```
                    Application
                         │
                         ▼
                    AudioCapture
                         │
                         ▼
                 Default output device
                         │
                ┌────────┴────────┐
                │                 │
             available         unavailable
                │                 │
                ▼                 ▼
             capture          recovery loop
                │                 │
                ▼                 │
          20 ms AudioFrame        │
                │                 │
                ▼                 │
             consumer             │
                                  │
                    device appears│
                         ┌────────┘
                         ▼
                      capture
```