# ADR-020: Audio Ownership Boundries

## Decision
```
Audio Capture
    Owns:
    - device interaction
    - WASAPI interaction
    - raw frame acquisition
    - frame timestamps
    - capture lifecycle
    - capture recovery

    Does NOT own:
    - speech detection
    - semantic buffering
    - transcription
```
```
Audio Processing
    Owns:
    - format normalization
    - resampling
    - channel conversion
    - semantic buffering

VAD
    Owns:
    - speech start
    - speech end
    - speech segmentation
```

| Concern                             | Owner                  |
| ----------------------------------- | ---------------------- |
| Native frame acquisition            | Capture adapter        |
| Transport queue                     | Capture subsystem      |
| **20 ms processing-frame assembly** | **AudioNormalizer**    |
| Sample-rate conversion              | Audio processing       |
| Channel conversion                  | Audio processing       |
| Speech buffering                    | SpeechSegmentAssembler |
| Speech segmentation                 | SpeechSegmentAssembler |

| Concern                    | Owner                  |
| -------------------------- | ---------------------- |
| Speech start/end detection | VAD                    |
| Transcription chunks       | Transcription pipeline |


### audio capture subsystem architectural boundary
The audio capture subsystem is responsible only for acquiring continuous audio and exposing timestamped audio frames. It has no knowledge of speech detection, speech segments, VAD, transcription, or semantic chunking.