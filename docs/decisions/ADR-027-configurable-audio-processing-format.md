# ADR-027: Configurable Audio Processing Format

## Status

Accepted

## Context/Reason

The audio capture layer produces audio in the native format of the selected
WASAPI loopback device.

The downstream processing pipeline requires audio to be normalized into a
deterministic processing format.

The project already contains `AudioProcessingSettings` with configurable
sample rate and channel count. The audio contracts also contained hard-coded
processing-format constants, creating two potential sources of truth.

The system should remain configuration-driven while keeping downstream
processing components independent from the application configuration
infrastructure.

## Decision

`AudioProcessingSettings` is the single source of truth for the target
processing sample rate and channel count.

`AudioNormalizer` receives `AudioProcessingSettings` through dependency
injection.

The processing frame duration remains a fixed architectural invariant of
20 ms.

The number of samples per processing frame is derived from the configured
sample rate:

    frame_samples = sample_rate × 0.020

`ProcessingAudioFrame` explicitly carries its `AudioFormat`.

The normalizer is responsible for:

- sample-rate conversion;
- channel conversion;
- sample-type conversion to float32;
- stateful buffering;
- exact 20 ms framing.

The normalizer does not access global configuration.

## Rationale

This provides a single source of truth for processing configuration while
retaining a deterministic framing contract.

It also keeps the normalizer independently testable and replaceable through
dependency injection.

Deriving frame size from the configured sample rate prevents the frame size
from becoming a second independently configurable value.

## Consequences

### Positive

- No duplicated processing-format configuration.
- Processing format can be changed without modifying source code.
- Frame size is always derived correctly from sample rate.
- The normalizer remains independent of configuration loading.
- Downstream components receive an explicit processing format.
- The processing frame duration remains stable.

### Negative

- `ProcessingAudioFrame` becomes slightly more explicit.
- Tests must provide processing settings.
- Downstream components must handle the configured processing format.
- Different sample rates result in different numbers of samples per 20 ms
  frame.

## Alternatives Considered

### Hard-code 16 kHz mono

Rejected because it conflicts with the project's configuration-driven design
and duplicates the information already represented by
`AudioProcessingSettings`.

### Keep both constants and settings

Rejected because this creates two sources of truth and allows the configured
processing format to diverge from the contract.

### Configure frame size independently

Rejected because frame size is mathematically derived from the configured
sample rate and the fixed 20 ms processing-frame duration.

### Allow arbitrary processing frame durations

Rejected because 20 ms is the established framing boundary for the VAD
pipeline and should remain deterministic.

## Related Components

- `AudioProcessingSettings`
- `AudioNormalizer`
- `ProcessingAudioFrame`
- VAD processing pipeline