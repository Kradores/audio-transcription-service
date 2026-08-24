## Configuration Subsystem

- Introduced immutable typed configuration models using Pydantic.
- Added YAML configuration loader with custom exceptions.
- Added comprehensive unit tests covering happy paths, validation, boundary values, immutability, and nested models.
- Established reusable testing infrastructure with builders and fixtures.
- Configured Ruff, MyPy, Pytest, and editable package installation.

## Configuration milestone

We now have:
- `config/config.yaml` populated
- `config/config.example.yaml` populated
- Empty unused fixture directory removed
- Real default configuration tested through `ConfigurationLoader`
- Existing configuration unit tests still passing
- Path typing expectations corrected
- `pytest` — 37/37 passed
- `ruff check .` — passed
- `mypy .` — passed


## Sprint 2 status

We have successfully completed:

1. Configuration
    - Production config/config.yaml
    - config/config.example.yaml
    - Removed unused fixtures
    - Default configuration integration test
    - 37 tests passing
    - Ruff + mypy green

2. Logging
    - ADR-017 accepted
    - app/core/logging.py
    - Standard-library logging
    - Configurable log level
    - Console output
    - Consistent structured format
    - No duplicate handlers
    - 4 dedicated logging tests
    - Full quality gate green


## As of [2026-08-10]
**Implemented**
### Sprint 2
- configuration
- logging
- composition
- application lifecycle
- startup

### Architecture
- ADR-018 Audio Capture
- ADR-019 Recovery
- ADR-020 Ownership
- ADR-021 Normalization
- ADR-022 Lifecycle
- ADR-023 VAD / buffering semantics
- ADR-024 VAD contract
- ADR-025 Segment assembler

### Contract slice
- AudioFormat
- AudioFrame
- ProcessingAudioFrame
- SpeechStart
- SpeechEnd
- SpeechSegment
- Audio configuration restructuring
- segment audio ownership

### Verification
- 67 tests
- Ruff
- Ruff format
- mypy

## As of 2026-08-16
**Implemented**
- transcription boundary and pipeline;
- TranscriptionResult;
- transcript recording;
- SQLite persistence;
- ADR-032;
- ADR-033;
- ADR-034;
- ADR-035;
- capture recovery/discontinuity propagation;
- processing-state reset;
- and we're now at 218 passing tests.

## As of [2026-08-25]
**Implemented**
- first real persisted system-audio transcript;
- transcription execution decoupled from real-time processing;
- bounded non-blocking transcription queue;
- overload rejection without crashing the service;
- shared conversation timeline;
- system-audio and microphone source identity;
- two independent source-processing pipelines;
- shared transcription executor;
- two-sided conversation persistence;
- Windows default-output recovery;
- Windows default-microphone recovery;
- notification-storm debounce / settled-device recovery;
- real hardware validation through repeated device switching;
- zero capture-frame drops during recent aggressive recovery test;
- long-running real two-person conversation test;
- per-source segmentation observability;
- transcription queue/backlog observability;
- queue-wait and transcription-duration statistics;
- Per-Source Speech Segment Aggregation Before Transcription Execution;
- file logging with rotating file;
- ADR-036;
- ADR-037;
- ADR-038;
- ADR-039;
- ADR-040;
- ADR-041;
- and we're now at 367 passing tests;
- full quality gate: Ruff, mypy, pytest.