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
### AudioCapture contract
- registration happens before start();
- replacing the handler while running is prohibited;
- callback is synchronous;
- callback is notification-only;
- callback does not reset downstream components directly;
- SpeechPipeline consumes the notification and coordinates reset.

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
- `confidence`: optional normalized `float`; its concrete meaning is adapter-defined;
- for `FasterWhisperTranscriber`, `confidence` is the detected-language probability returned by Faster-Whisper and is **not** a transcript-text accuracy score;
- `start` / `end`: transcription segment timestamps;
- represents one complete `SpeechSegment` transcription.

## Transcriber
```py
transcribe(segment: SpeechSegment) -> TranscriptionResult
```
The `Transcriber` contract is intentionally synchronous:
Execution scheduling is owned by the application pipeline.

The pipeline may execute the synchronous Transcriber through a dedicated
worker so that model inference does not block real-time audio processing.

The transcription execution mechanism is not part of the Transcriber
contract. Implementations must not depend on queue, worker, or concurrency
details.

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


