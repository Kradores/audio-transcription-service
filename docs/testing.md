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


## Realistic runtime and performance validation

Unit and integration tests protect deterministic behavior, but they do not
establish whether the complete local transcription service can keep up with a
real conversation on target hardware.

Performance and backpressure decisions must therefore include controlled
real-runtime validation.

### Long-running conversation test

For transcription-throughput investigations, run a realistic two-sided
conversation for at least 10–30 minutes.

The test should exercise:

```text
system audio
+
microphone
+
independent source pipelines
+
shared transcription executor
+
Faster-Whisper
+
SQLite persistence
```

The test is considered diagnostic rather than a deterministic automated test.

Record the following runtime configuration:

```text
Whisper model
Whisper device
compute type
transcription queue capacity
segmentation target duration
segmentation maximum duration
VAD configuration
machine/hardware used
```

At shutdown, preserve the final statistics from:

```text
SpeechPipeline(source=system_audio)
SpeechPipeline(source=microphone)
TranscriptionExecutor
```

The pipeline summaries should provide:

```text
captured_frames
processing_frames
segments_emitted
segments_rejected
short_segments
avg_segment_duration
max_segment_duration
```

The executor summary should provide:

```text
submitted
completed
rejected
failed
queue_high_water_mark
avg_queue_wait
max_queue_wait
avg_transcription_duration
max_transcription_duration
```

### What the test is intended to answer

The test should provide enough evidence to determine:

1. whether either capture path drops frames;
2. how many speech segments each source produces;
3. how frequently segments shorter than one second are produced;
4. whether either source disproportionately contributes to executor load;
5. whether the executor reaches queue capacity;
6. whether accepted work spends significant time waiting;
7. whether transcription duration is stable or varies under machine load;
8. how many segments are rejected;
9. whether graceful shutdown drains all accepted work.

### Throughput comparisons

When comparing performance strategies, change one major variable at a time.

Examples:

```text
baseline single worker
vs.
segment aggregation

baseline single worker
vs.
two workers

aggregation only
vs.
aggregation + multiple workers
```

Use the same or comparable conversation/audio workload where practical.

Do not select a throughput strategy solely because one synthetic benchmark is
faster.

The service runs on user hardware alongside other applications, so stability,
resource usage, rejection rate, and queue latency are all relevant.

### Success criteria

There is currently no fixed universal performance threshold.

The immediate goal is to collect enough evidence to choose between:

```text
segment aggregation
additional worker capacity
combination of both
```

without compromising the existing guarantees:

- real-time capture must remain non-blocking;
- queues remain bounded;
- sustained overload must not crash the service;
- capture and transcription pressure remain independently observable.


## Coordinated Windows PortAudio refresh

Default-device recovery requires both deterministic unit tests and real
hardware validation.

Unit tests must not attempt to reproduce Windows or PortAudio itself.

They verify application-owned lifecycle semantics using fakes and controlled
async scheduling.

### Coordinator behavior

Tests cover:

- all registered capture participants are disposed before any participant is
  recreated;
- the notification-settle period begins only after all participants are
  disposed;
- duplicate and concurrent notifications are coalesced;
- shared refresh generation advances immediately when a device-change signal
  arrives;
- notifications arriving while a refresh caller is already awaiting the
  coordinator extend the same logical refresh;
- a later `request_refresh()` is a no-op when that generation was already
  completed;
- expected `LookupError`/`OSError` from one participant restoration does not
  prevent restoration attempts for other participants;
- unexpected restoration failures remain visible;
- teardown attempts all participants before reporting teardown failure.

### Capture behavior

Capture tests cover:

- matching default-device notifications request process-wide refresh;
- ordinary inactive-stream failure remains source-local;
- coordinated preparation disposes the capture's native PortAudio session;
- source-local native reopening is suspended while coordinated refresh is
  active;
- coordinated restoration opens a fresh source-owned session;
- failure during coordinated restoration re-enables source-local recovery;
- startup device-discovery `LookupError` and `OSError` enter recovery instead
  of terminating the service;
- recovery backoff is interruptible by a default-device notification;
- microphone discovery uses WASAPI `defaultInputDevice`;
- an input device with no input channels is rejected;
- the generic PortAudio default-input lookup is not used for microphone
  selection.

### Composition behavior

Composition tests prove:

- one `PortAudioRefreshCoordinator` is created for the conversation;
- the same coordinator is injected into both captures;
- both captures are registered as refresh participants;
- each capture retains its own device-provider policy and native session.

### Real-device validation matrix

The automated suite cannot establish whether Windows and PortAudio actually
refresh native enumeration correctly.

ADR-043 therefore requires manual real-device validation on Windows.

Validated scenarios:

| Scenario | Expected result |
| --- | --- |
| Headphones → Speakers in Windows Settings | system capture follows Speakers |
| Speakers → Headphones in Windows Settings | system capture follows Headphones |
| Headset → Microphone Array in Settings | microphone follows Microphone Array |
| Microphone Array → Headset in Settings | microphone follows Headset |
| Physical headset disconnect | current Windows defaults are rediscovered |
| Physical headset reconnect | current Windows defaults are rediscovered |
| Start with no usable microphone | application remains alive |
| Enable microphone after startup | microphone joins running conversation |
| Notification burst | one coordinated refresh |
| Application shutdown after refresh | clean shutdown |

Validation must inspect:

- selected device name;
- native channel count;
- native sample rate;
- refresh generation behavior;
- source discontinuity delivery;
- continued shared conversation timestamps;
- `frames_dropped`;
- clean shutdown.

The latest ADR-043 validation completed with:

```text
402 passed
2 existing PyTorch/Python 3.14 deprecation warnings

mypy:
Success: no issues found in 103 source files

ruff:
All checks passed
```

The two warnings originate from `torch.jit.load` under Python 3.14 and are not
related to audio-device recovery.


## AMD / TheRock transcription validation

AMD support has multiple validation levels.

They intentionally test different failure boundaries.

### Normal preparation acceptance

The normal entry point is:

```powershell
.\scripts\amd\prepare.ps1
```

This validates:

- pinned build prerequisites;
- exact CTranslate2 source revision;
- HIP + Intel OpenMP native configuration;
- native DLL dependencies;
- custom wheel packaging;
- fresh TheRock runtime installation;
- exact script-produced CTranslate2 DLL loading;
- GPU discovery;
- `float16` support;
- real Faster-Whisper inference;
- model destruction;
- child-process exit;
- application dependency compatibility;
- CPU-only PyTorch/Silero behavior;
- preservation of the custom CTranslate2 runtime after application dependency
  installation.

Developers should not manually run every stage script for ordinary setup.

Individual scripts remain directly executable for stage-specific diagnosis.

### Sustained teardown regression

The long-running native lifecycle test is:

```powershell
.\scripts\amd\test_long_runtime.ps1
```

or as part of complete preparation:

```powershell
.\scripts\amd\prepare.ps1 `
    -RunLongValidation
```

The validated 20-minute run produced:

```text
transcriptions=1039
duration_seconds=1200.3
average_inference_seconds=1.155
maximum_inference_seconds=1.633
model_destruction_seconds=0.044
exit_code=0
```

This test exists specifically because the original CTranslate2
`OPENMP_RUNTIME=NONE` build could pass short inference tests and still deadlock
during sustained-use teardown.

A short smoke test is therefore not considered sufficient evidence for native
shutdown correctness.

### Real application AMD acceptance

The final acceptance test must use the complete application:

```text
system_audio
+
microphone
+
CPU Silero
+
per-source aggregation
+
shared executor
+
AMD Faster-Whisper
+
SQLite persistence
```

The validated application run produced:

```text
system_audio frames_dropped=0
system_audio segments_rejected=0

microphone frames_dropped=0
microphone segments_rejected=0

worker_count=1
submitted=166
completed=166
rejected=0
failed=0
queue_high_water_mark=2
avg_queue_wait=0.191
```

Graceful shutdown completed after draining and persisting the final accepted
transcription.

The Python process then returned normally.

This real application test is the final acceptance boundary for the current
AMD integration.