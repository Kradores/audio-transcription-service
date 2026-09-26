# ADR-057 — Platform-Specific Composition, Source Ownership, and Quality Gates

## Status Proposed

## Context

Audio Transcription Service is expanding from Windows-only operation to Windows and Linux.

The majority of the application is already platform-independent, including audio contracts and normalization, speech processing, VAD, transcription orchestration, persistence, model provisioning, and application services.

Existing Windows infrastructure includes WASAPI/PyAudioWPatch capture, PyCAW device monitoring, Windows shell integration, Windows GPU runtime initialization, Windows process control, and Windows packaging.

Initial Linux validation demonstrated that platform-independent dependencies can be installed successfully on Linux and that shared application contracts can be imported.

However, the current composition root directly imports Windows audio implementations. Consequently, otherwise portable ML, VAD, replay, application, and composition tests cannot even be collected on Linux.

Running mypy on Linux also exposes Windows-only standard-library APIs in Windows-specific components.

## Decision

The repository will distinguish explicitly between platform-independent application code and platform-specific infrastructure.

Shared application and domain modules must not import Windows- or Linux-specific infrastructure implementations.

Operating-system-specific infrastructure will depend inward on application-owned contracts.

Platform adapters must not leak their implementation-specific dependencies into shared contracts.

Application composition will consist of a shared composition layer and explicit platform-specific composition at the outer boundary.

The shared composition layer may construct platform-independent services but will receive platform-dependent capabilities through dependency injection.

Windows composition will construct Windows adapters such as WASAPI capture, Windows audio-device monitoring, PortAudio refresh coordination, and Windows-specific runtime infrastructure.

Linux composition will later construct the corresponding Linux implementations.

Scattered `sys.platform`, `os.name`, conditional imports, and `try/except ImportError` blocks will not be used as the mechanism for making shared application code portable.

A single outermost platform-selection point is permitted when required by an executable entry point.

Tests will follow the same ownership model.

Platform-independent tests will execute on every supported operating system.

Windows-specific tests will execute on Windows.

Linux-specific tests will execute on Linux.

Platform-specific tests will be excluded before module import on unsupported operating systems so missing platform dependencies do not cause collection failures.

Hardware tests remain platform-specific acceptance tests and do not become requirements for ordinary unit-test execution.

Static typing will follow source ownership.

Shared source code must pass mypy on every supported development platform.

Windows-specific source code must pass mypy in the Windows quality gate.

Linux-specific source code must pass mypy in the Linux quality gate.

Platform-specific source code will not be globally excluded from mypy merely to make another operating system's quality gate pass.

Ruff remains applicable across the complete Python source tree because it does not require loading platform runtime dependencies.

The existing Windows quality gates must remain intact while Linux support is introduced.

## Consequences

Positive:

- shared code becomes genuinely importable and testable on both platforms;
- platform dependencies remain at infrastructure boundaries;
- Windows support does not need Linux compatibility hacks;
- Linux adapters can evolve without changing Windows implementations;
- shared tests provide regression coverage across both operating systems;
- each platform retains strong typing for its own infrastructure;
- future CI can clearly express shared, Windows, Linux, and hardware validation.

Negative:

- some existing modules and tests must be reorganized;
- there will be more than one platform composition root;
- platform-specific quality-gate orchestration is required;
- some code currently residing in broadly named modules will need more explicit ownership;
- Windows and Linux acceptance ultimately require separate OS environments.

## Alternatives considered

**Scatter platform conditionals through current modules** — rejected because it obscures dependency boundaries and makes shared code progressively harder to reason about.

**Install or mock Windows dependencies on Linux** — rejected because it produces misleading validation and couples Linux development to Windows implementation details.

**Globally ignore Windows files in mypy** — rejected because Windows-specific production code would lose static-type coverage.

**Maintain completely independent Windows and Linux applications** — rejected because the processing pipeline, transcription, persistence, configuration, and much of application composition are naturally shared.

**Duplicate the entire composition root per operating system** — rejected because most construction logic is platform-independent and duplication would invite behavioral drift.

**Use pytest markers alone** — rejected as the sole platform boundary because test modules must be imported before their markers can control execution.

## Related decisions

- ADR-005 — Architectural Boundaries
- ADR-015 — Testing Philosophy
- ADR-016 — Application Composition Root
- ADR-018 — Audio Capture Architecture
- ADR-039 — Multi-Source System and Microphone Audio Processing Architecture
- ADR-044 — AMD GPU Transcription Runtime and CPU Fallback Strategy
- ADR-049 — Windows End-User Packaging
- ADR-050 — Controller and Runtime Process Boundary
- ADR-056 — Linux Development and Native Hardware Acceptance Environment Strategy
