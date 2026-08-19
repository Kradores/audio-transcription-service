## First rule
I don't want tests to just verify behavior - I want them to describe the component.

## Test structure
```
tests/
├── integration/
    └── core/
        └── config/
            └── test_default_configuration.py
└── unit/
    └── core/
        ├── test_logging.py
        └── config/
            ├── builders.py
            ├── helpers.py
            ├── test_loader.py
            └── test_models.py
```

## Test philosophy
- Loads a valid configuration
- Raises `ConfigurationFileNotFoundError`
- Raises `ConfigurationParsingError`
- Raises `ConfigurationValidationError`
- Resolves relative paths
- Leaves absolute paths unchanged

## Test naming
Use this format consistently:
```
def test_load_returns_settings_for_valid_configuration() -> None:
```

## Testing pattern
```
# Arrange

# Act

# Assert
```
One blank line between Arrange, Act and Assert

## What a unit test does
A unit test should verify one component's responsibility. Avoid re-testing behavior already covered by another test suite.
For example:
- `test_loader.py` verifies loading, parsing, validation, and path resolution.
- `test_models.py` verifies field constraints and model behavior.

That separation keeps the tests fast, focused, and easier to maintain.

## Coverage philosophy

One thing I don't want.

I don't want:
- 100% line coverage.

I want:
- 100% confidence.

Those are different.
One boundary-value test is worth more than five trivial "happy path" tests.

## Testing philosophy
- Test behavior, not implementation.
- Prefer boundary values over arbitrary invalid values.
- Use builders to construct valid objects.
- Use parameterized tests when the behavior is identical.
- Every ADR that affects runtime behavior should have at least one test protecting it.
I genuinely think this last point is one of the strongest ideas we've developed during this project. If an architectural decision is important enough to deserve an ADR, it's usually important enough to deserve a test that will alert us if someone accidentally breaks it in the future.

## Test Structure

Within a test file, organize tests by the production type they verify (e.g., one section per model), and within each section group them as:
- Happy path
- Boundary validation
- Invalid input
- Special behavior (immutability, computed properties, etc.)

That's exactly the structure we're using here, and I think it will scale beautifully as the project grows.

## Pydantic validation failures
When testing Pydantic validation failures, prefer model_validate() with dictionaries over constructing models with statically invalid arguments.
This has several benefits:
- Keeps MyPy completely green.
- Mirrors production usage (configuration is parsed from dictionaries).
- Avoids fighting the type checker.
- Makes tests more expressive for invalid input scenarios.

## audio testing strategy
```
AudioCapture
    ├── contract/unit tests
    └── Windows integration tests

AudioNormalizer
    └── deterministic unit tests

SileroVADAdapter
    ├── adapter contract tests
    └── model integration tests where practical

SpeechSegmentAssembler
    └── deterministic state-machine tests

Storage testing
├── TranscriptRecorder
│   └── deterministic unit tests with repository fake/mock
│
└── SQLiteTranscriptRepository
    └── real SQLite tests using :memory:
```

And specifically test:
- 200 ms pre-roll
- 200 ms post-roll
- speech resuming during post-roll
- ~3 s target
- 5 s hard split
- 10/15 s experimental configurations
- no overlap
- frame ownership
- capture interruption
- shutdown discard
- maximum-duration invariant
- SQLite repository tests use real SQLite;
- `:memory:` is used to avoid filesystem dependency;
- schema initialization is tested;
- insertion/persistence is tested;
- nullable confidence is tested;
- append-only behavior is tested;
- commit behavior is tested;
- database failures propagate;
- composition tests verify database construction/wiring;
- lifecycle tests verify the database connection is closed during application shutdown.

### Unit tests
No Windows audio hardware required.

Use a deterministic fake implementation that generates known frames.

Test:
- frame ordering
- timestamps
- lifecycle
- cancellation
- bounded queue
- overflow behavior
- frame drops
- consumer behavior

### Integration tests
Run on Windows where appropriate.

Test the actual PyAudioWPatch adapter:

- device discovery
- loopback opening
- actual frame acquisition
- format reporting
- startup/shutdown
- potentially device recovery

This keeps CI/test architecture clean.


## Transcription execution testing

The transcription execution boundary must be tested independently from the
real-time audio processing components.

### Required behavior

Tests must verify:

- speech segments are accepted without waiting for transcription completion;
- transcription work is processed by the configured worker;
- the synchronous `Transcriber` contract remains unchanged;
- transcription results are delivered through the existing result handler;
- submitted segments are processed in chronological order;
- transcription failures are observable and follow the configured failure
  semantics;
- shutdown handles queued transcription work deterministically;
- an in-progress transcription does not cause the audio-processing loop to
  stop consuming capture frames;
- the transcription queue is bounded.

### Throughput/backpressure tests

Tests should distinguish the two buffering boundaries:

```text
AudioCapture
    ↓
capture transport
    ↓
real-time audio processing
    ↓
transcription queue
    ↓
transcription worker

Capture queue capacity must not be used as the mechanism for absorbing normal
transcription inference latency.

The transcription queue's capacity and overflow behavior must be tested
independently.
```

**Real ML integration**
Real Faster-Whisper integration tests continue to validate the transcriber
implementation itself.

End-to-end runtime tests additionally verify that real transcription does not
cause capture-frame loss under the expected workload.

The last point is particularly important because we now have a real regression criterion:
```py
frames_dropped = 0
```
for the controlled workload.


### Windows default-output recovery

Default-output recovery is tested at multiple boundaries.

Unit tests verify:

- Windows audio-device monitor lifecycle;
- filtering for the relevant default render endpoint change;
- delivery of the endpoint-change notification;
- capture recovery when the default output changes;
- PyAudio reinitialization and fresh device discovery;
- recovery coalescing when multiple recovery signals occur;
- downstream discontinuity signaling;
- continued retry when no usable default loopback is immediately available.

Real-hardware validation verifies behavior that cannot be represented reliably
through mocks alone.

The recovery path has been validated by switching the Windows default output
in both directions between speakers and Bluetooth headphones with different
native sample rates.

The expected result is:

- the application remains running;
- the new default WASAPI loopback endpoint is selected;
- capture resumes;
- processing state is reset at the discontinuity;
- transcription and persistence continue;
- shutdown remains clean.

The test does not require zero audio loss during the Windows device transition.

Windows may take several seconds to remove, discover, activate, and select
audio endpoints. Audio unavailable during that operating-system transition is
outside the capture recovery guarantee.

The important invariant is that once Windows exposes a usable default output
endpoint, the application recovers automatically without restart.