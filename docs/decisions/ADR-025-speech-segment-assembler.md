# ADR-025: SpeechSegmentAssembler

## Decision
Architecture:
```
                    ProcessingAudioFrame
                            │
                            ▼
                     VAD result
                            │
                            ▼
                 SpeechSegmentAssembler
                            │
             ┌──────────────┴──────────────┐
             │                             │
           IDLE                         SPEAKING
             │                             │
        SpeechStart                 SpeechEnd / max
             │                             │
             ▼                             ▼
         pre-roll                    post-roll / split
             │                             │
             └──────────────┬──────────────┘
                            ▼
                     SpeechSegment
```

State machine:
```
                         ┌──────────┐
                         │   IDLE   │
                         └────┬─────┘
                              │
                       SpeechStart
                              │
                              ▼
                       ┌────────────┐
                       │  SPEAKING  │
                       └─────┬──────┘
                             │
                 ┌───────────┼─────────────┐
                 │           │             │
            SpeechEnd    max duration   capture lost
                 │           │             │
                 ▼           ▼             ▼
          ┌────────────┐   emit         emit
          │POST_SPEECH │     │             │
          └──────┬─────┘     │             │
                 │            │             │
        ┌────────┴───────┐    │             ▼
        │                │    │           IDLE
   speech resumes   post-roll
        │            complete
        ▼                │
    SPEAKING             ▼
                       emit
                         │
                         ▼
                        IDLE
```

When max duration is reached while continuously speaking:
```
SPEAKING
   │
   ▼
emit Segment A
   │
   ▼
SPEAKING
```

The resulting invariants:
Invariant 1
Every emitted segment contains only normalized audio.

Invariant 2
Every frame belongs to at most one segment.
No overlap initially.

Invariant 3
Pre-roll is used only when speech begins from IDLE.

Invariant 4
Post-roll is included only after a natural speech end.

Invariant 5
No emitted segment exceeds the configured maximum duration.

Invariant 6
A capture interruption never creates a segment spanning the gap.

Invariant 7
Shutdown never emits an incomplete segment.

Invariant 8
The assembler does not depend on Silero.
It consumes our VAD contract.


| Decision             | Initial value                                      |
| -------------------- | -------------------------------------------------- |
| Pre-roll             | 200 ms                                             |
| Post-roll            | 200 ms                                             |
| Target duration      | ~3 s                                               |
| Maximum duration     | 5 s                                                |
| Maximum boundary     | **Hard split**                                     |
| Segment overlap      | None                                               |
| Capture interruption | Terminate current segment                          |
| Shutdown             | Discard incomplete segment                         |
| Padding ownership    | Our assembler initially; test against Silero later |
| Frame size           | 20 ms                                              |
| Segment audio        | Owned `float32` NumPy array                        |


When the 5-second maximum is reached during continuous speech, the segment is emitted immediately and the assembler remains in `SPEAKING` for the next segment.
