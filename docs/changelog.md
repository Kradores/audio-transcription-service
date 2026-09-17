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


## As of 2026-09-01

**Implemented**

- optional AMD GPU Faster-Whisper transcription on Windows;
- TheRock/HIP runtime support for the validated `gfx1031` target;
- custom CTranslate2 4.8.1 Windows HIP wheel;
- Intel OpenMP CTranslate2 build fixing the sustained-use shutdown deadlock;
- explicit `default` and `therock` Whisper runtime selection;
- delayed CTranslate2/Faster-Whisper import after backend runtime initialization;
- CPU Silero VAD + AMD GPU Whisper hybrid execution;
- AMD transcription default of one executor worker;
- fail-fast behavior for explicitly configured but unavailable TheRock runtime;
- reproducible AMD prerequisite, source, build, wheel, smoke, sustained, and
  application-runtime validation scripts;
- single normal AMD preparation entry point:
  `scripts/amd/prepare.ps1`;
- 20-minute sustained GPU teardown validation;
- complete two-source real application AMD acceptance with zero capture drops,
  zero transcription rejection, zero transcription failures, and clean
  shutdown;
- ADR-044.


## As of 2026-09-06

**Implemented**

- corrected cross-source conversation timestamps so system loopback silence no
  longer compresses the `system_audio` timeline while microphone capture
  continues;
- preserved real source-timeline gaps through audio normalization;
- validated system-audio and microphone timestamp alignment after long
  loopback-silence periods;
- added configurable transcription language modes:
  `auto`, `fixed`, and `adaptive`;
- added independent conversation-scoped adaptive language state per audio
  source;
- added probe-based language establishment, candidate confirmation, language
  switching, and low-confidence fallback;
- short speech now uses an established source language explicitly instead of
  independently re-detecting language when adaptive mode has context;
- added structured adaptive-language decision logging;
- added microphone language-detection benchmark tooling using exact captured
  transcription segments;
- confirmed that microphone signal level can materially affect Faster-Whisper
  language-detection probability;
- added configurable microphone transcription gain through
  `transcription.microphone_gain_db`;
- microphone gain defaults to `0.0 dB` and is applied only immediately before
  transcription;
- system audio remains unchanged by microphone gain configuration;
- added replaceable `TranscriptionAudioPreprocessor` implementations for
  identity and fixed gain;
- excessive configured gain is clipped to the normalized audio range and
  reported through structured warning logs;
- full quality gate green:
  - `480 passed`;
  - mypy clean across `117` source files;
  - Ruff formatting and linting clean.


## As of 2026-09-17

**Implemented**

- Windows NVIDIA Faster-Whisper distribution;
- ADR-051 — Windows NVIDIA Faster-Whisper Runtime Distribution;
- separate CPU, NVIDIA, and AMD Windows build profiles;
- `WhisperRuntime.NVIDIA`;
- `NvidiaFasterWhisperRuntimeInitializer`;
- application-private NVIDIA CUDA runtime initialization before CTranslate2 import;
- explicit NVIDIA runtime directory injection from the Windows packaging boundary through the spawned transcription runtime process;
- pinned NVIDIA runtime:
  - `nvidia-cublas-cu12==12.4.5.8`;
  - `nvidia-cudnn-cu12==9.1.0.70`;
  - `nvidia-cuda-nvrtc-cu12==12.4.127`;
- reproducible NVIDIA runtime staging from official NVIDIA packages;
- dedicated NVIDIA PyInstaller `onedir` distribution;
- dedicated NVIDIA Inno Setup installer;
- NVIDIA-specific default configuration template while preserving the single shared user `config.yaml`;
- standalone NVIDIA CUDA/Faster-Whisper smoke-test artifact;
- NVIDIA RTX 2080 smoke validation with CTranslate2 4.8.1 and Faster-Whisper 1.2.1 using CUDA `float16`;
- full external NVIDIA application acceptance on RTX 2080;
- simultaneous microphone and system-audio transcription through the production NVIDIA installer;
- 99 transcription jobs submitted and completed with zero rejection and zero failures;
- zero capture-frame drops on both microphone and system audio;
- graceful NVIDIA runtime shutdown and successful support-bundle generation;
- substantial reduction in transcription latency and executor queue pressure compared with the previous CPU acceptance run;
- Windows CPU installation/runtime behavior kept unchanged;
- full quality gate green:
  - 572 tests passed;
  - Ruff format clean;
  - Ruff check clean;
  - mypy clean across 157 source files.

**Known follow-up**

- improve support-bundle packaged dependency detection;
- include GPU, driver, and packaged accelerator-runtime versions in support diagnostics;
- defer NVIDIA installer/runtime-size optimization until there is evidence that the current size is operationally problematic.