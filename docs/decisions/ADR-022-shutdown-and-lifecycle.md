# ADR-022: Shutdown and Lifecycle

## Decision
| Area                       | Decision                          |
| -------------------------- | --------------------------------- |
| Lifecycle owner            | `AudioPipeline` / application     |
| Capture API                | `start()` / `frames()` / `stop()` |
| `frames()` starts capture? | **No**                            |
| Normal shutdown            | Stream ends normally              |
| Consumer wake-up           | Queue closure/sentinel            |
| Recovery                   | Stream remains alive              |
| Recovery delay             | Cancellation-aware                |
| Queued frames on shutdown  | Discard                           |
| Component restartability   | **No initial restart API**        |
| Startup failure            | Raise/fail startup                |
| `stop()` idempotent        | **Yes**                           |
| `stop()` before `start()`  | Harmless                          |
| Native thread ownership    | Capture adapter                   |
| Lifecycle state            | Internal + observable             |

**In-progress processing** completes or is cancelled according to component shutdown semantics; incomplete audio segments are discarded.

### Ordering of shutdown
1. Signal pipeline shutdown.
2. Stop AudioCapture from producing new frames.
3. Close the capture stream and discard queued frames.
4. Stop/cancel downstream processing.
5. Discard incomplete speech-segmentation state.
6. Release resources.
7. Application exits.

### Who owns the lifecycle?
The pipeline/application owns lifecycle orchestration.

Individual components own their own internal resources.

```
Application.start()
       │
       ▼
AudioPipeline.start()
       │
       ├── capture.start()
       ├── normalizer.start()
       └── processing starts
```
```
Application.stop()
       │
       ▼
AudioPipeline.stop()
       │
       ├── stop accepting new capture
       ├── stop capture
       ├── terminate/close queue
       └── stop processing
```
This prevents components from knowing about their siblings.