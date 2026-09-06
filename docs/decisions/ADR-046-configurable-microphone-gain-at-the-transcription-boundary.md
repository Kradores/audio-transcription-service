# ADR-046: Configurable Microphone Gain at the Transcription Boundary

## Status
Accepted

### Date
2026-09-05

## Context

The microphone transcription investigation found that Faster-Whisper language detection is sensitive to microphone signal level.

Controlled experiments using identical captured microphone `SpeechSegment` audio demonstrated that changing only signal gain could materially change language-detection probability. Moderate gain improved several difficult English and Romanian samples, while stronger amplification or normalization was not uniformly better.

A real conversation test using `+12 dB` microphone transcription gain at a Windows microphone level of 33 produced successful Romanian → English → Romanian adaptive-language switching without clipping.

Additional experiments using Windows microphone levels 66 and 100 showed that the Windows input control does not provide a predictable or portable relationship to the captured digital signal. Microphone hardware, Bluetooth DSP, drivers, Windows processing, user speaking level, and microphone placement can all affect the resulting audio.

Therefore the application cannot assume a universally correct microphone gain.

Automatic normalization or automatic gain control has not been sufficiently validated and could degrade microphones that already provide appropriate signal levels.

## Decision

The application will support an **optional configurable gain applied only to microphone audio immediately before transcription**.

The default will be:

```yaml
transcription:
  microphone_gain_db: 0.0
```

`0.0 dB` means no modification and preserves existing behavior.

Positive values amplify microphone transcription audio. Negative values attenuate it.

The configuration will be documented as an optional transcription-quality tuning control whose useful value depends on the microphone, operating-system configuration, driver/DSP behavior, environment, and speaker.

The gain will be applied after:

```text
capture
→ normalization
→ VAD
→ segment assembly
→ aggregation
```

and before creation/submission of the audio used for Whisper transcription.

Therefore gain does not influence:

```text
capture behavior
VAD decisions
segment boundaries
aggregation policy
timestamps
```

System audio will not receive this gain.

The transformation will create a new `SpeechSegment` rather than mutate the existing segment's audio buffer.

Audio exceeding the valid normalized float range will be clipped to:

```text
[-1.0, 1.0]
```

Clipping will be observable rather than silently changing the configured gain.

## Component boundary

The gain transformation will not be implemented as gain-specific logic embedded permanently in `SpeechPipeline`.

A small replaceable transcription-audio preprocessing boundary will be used conceptually as:

```text
SpeechPipeline
    ↓
TranscriptionAudioPreprocessor
    ↓
TranscriptionExecutor
```

Composition will provide the appropriate implementation per source.

Initially:

```text
microphone
→ configured fixed-gain processor

system_audio
→ identity/no-op processor
```

This keeps orchestration separate from signal-processing policy and allows the preprocessing implementation to be replaced later if measurements justify another strategy.

## Configuration semantics

The configured value represents a deterministic decibel adjustment.

Conceptually:

```text
linear_gain = 10 ** (gain_db / 20)
```

Examples:

```text
  0 dB → 1.00×
 +6 dB → ~2.00×
+12 dB → ~3.98×
 -6 dB → ~0.50×
```

No automatic gain selection will occur.

The application will not inspect Windows microphone volume and attempt to derive a corresponding software gain.

## Default behavior

The default is:

```text
microphone_gain_db = 0.0
```

This is intentional.

Users who do not need tuning receive the microphone signal unchanged.

Users experiencing weak microphone transcription or unstable language detection may experiment with the setting based on their hardware and environment.

## Observability

At startup, the effective microphone transcription gain should be observable.

When clipping occurs, structured logging should expose enough information to diagnose the configuration, including at minimum:

```text
source
gain_db
input_peak
clipped_samples
```

Normal gain processing should not require verbose per-segment INFO logging once the diagnostic investigation is complete.

Transcript text must not be added to gain-processing logs.

## Testing

Tests should cover at least:

- `0 dB` preserves audio values;
- positive gain amplifies as expected;
- negative gain attenuates as expected;
- output retains `float32`;
- output remains contiguous;
- timestamps are unchanged;
- duration is unchanged;
- audio format is unchanged;
- the input `SpeechSegment` is not mutated;
- values exceeding valid range are clipped;
- clipping is observable;
- microphone composition receives configured gain;
- system audio remains unchanged;
- default configuration is `0.0 dB`.

## Consequences

### Positive

The application does not impose one microphone level on every user.

Existing installations retain identical behavior by default.

Users can tune signal level for their own hardware.

The configuration is explicit and reproducible.

Gain affects Whisper without changing VAD or segmentation behavior.

The preprocessing implementation remains replaceable.

Clipping can be diagnosed rather than silently damaging transcription quality.

### Negative

Users may choose a gain that makes transcription worse.

Excessive positive gain can clip audio.

Finding an optimal value remains hardware- and environment-specific.

An additional preprocessing component/configuration setting increases system complexity slightly.

The application does not automatically optimize microphone level for the user.

## Alternatives considered

**Fixed +12 dB for all microphones — rejected.** It worked well for one tested Razer configuration, but another microphone may already provide a high-level signal and could clip or degrade.

**Automatic peak normalization — rejected for now.** Experiments showed that aggressive normalization was not uniformly beneficial.

**Automatic RMS normalization — rejected for now.** It could drive some samples excessively hard and degraded some measured language probabilities.

**Automatic gain control — rejected for now.** No sufficiently reliable policy has been validated, and hidden adaptive behavior would make transcription harder to reason about and reproduce.

**Require users to adjust Windows microphone volume — rejected.** Experiments showed no reliable portable relationship between the Windows slider value and captured speech amplitude, and behavior will vary by hardware/driver.

**Apply gain before VAD — rejected.** That would couple transcription tuning to speech detection and segmentation behavior.

**Apply the same gain to system audio — rejected.** The investigation produced evidence only for microphone transcription audio.

## Follow-up

After ADR-046 is accepted, the first implementation slice should be deliberately small:

```text
1. config model + default 0 dB
2. tiny transcription-audio preprocessor contract
3. fixed-gain implementation
4. composition wiring
5. focused unit tests
```
