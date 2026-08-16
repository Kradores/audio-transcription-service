## Error messages
Every exception message should help the user fix the problem.

How not to do:
```
Validation failed.
```
The right way:
```
Invalid configuration in 'config/config.yaml': audio.sample_rate must be greater than or equal to 8000.
```

## AudioCapture
Lifecycle and streaming contract.

## AudioFrame
- samples
- sample_rate
- channels
- timestamp
- duration
with ownership/invariants.

## ProcessingAudioFrame
- float32
- 16 kHz
- mono
- 20 ms
- (samples, 1)

## VAD events
- SpeechStart
- SpeechEnd

## SpeechSegment
- audio
- timestamp
- duration
- format
with its invariants.

## TranscriptionResult
```
text
language
confidence
start
end
```
with:
- `confidence`: optional `float`;
- `start` / `end`: transcription segment timestamps;
- represents one complete `SpeechSegment` transcription.

## Transcriber
```py
transcribe(segment: SpeechSegment) -> TranscriptionResult
```
Synchronous.

## TranscriptionResultHandler
```py
(TranscriptionResult) -> None
```
The pipeline invokes it after successful transcription.

## TranscriptRecorder
```py
record(result: TranscriptionResult) -> None
```
Application-level persistence boundary.

## TranscriptRepository
```py
insert(result: TranscriptionResult) -> None
```
Append-only persistence contract.


