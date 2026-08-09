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
