# ADR-049: Windows End-User Packaging, Runtime Layout and Interactive Control Host

## Status

Accepted

## Context

The application has so far been developed and validated from a source checkout using Python development environments.

The next validation target is a separate Windows 11 machine owned by a nontechnical tester.

The developer has no direct access to that machine.

The tester must be able to install, start, stop and inspect the application without installing Python development tooling or executing terminal commands.

Remote diagnosis must be possible from files that the tester can easily collect and send.

The application captures both the Windows default render endpoint through WASAPI loopback and the Windows default microphone, and already owns coordinated startup and graceful shutdown through the application lifecycle.

The packaging approach must not introduce dependencies from the transcription/audio core onto installer or GUI concerns.

## Decision

Distribute the Windows application as a self-contained packaged runtime installed through a normal Windows installer.

The runtime will execute in the logged-in user's interactive session rather than as a Windows Service.

The initial packaging artifact will use PyInstaller `onedir` mode.

A Windows installer will place immutable application/runtime files separately from mutable per-user application data.

The mutable data root will contain configuration, SQLite persistence, logs, diagnostics and support bundles.

Existing configuration and transcript data must survive application upgrades.

A small Windows control host will provide the tester with explicit Start and Stop operations and convenient access to logs, configuration, transcript data and support-bundle creation.

The controller is an application entry point only. It delegates to the existing application composition/lifecycle and does not contain audio, transcription, VAD or persistence logic.

Graceful Stop must use the application's existing coordinated shutdown path rather than forcibly terminating the process.

The first externally tested installer will use the ordinary CPU Faster-Whisper runtime. NVIDIA acceleration will be validated as a separate subsequent deployment slice so packaging/audio portability and GPU-runtime portability are not diagnosed simultaneously.

The installed application must not depend on the process current working directory to locate mutable runtime data.

Support bundles will contain sufficient runtime/environment metadata to diagnose failures remotely. Inclusion of the transcript database must be explicit because it contains conversation content.

## Rationale

A per-user interactive application matches the actual usage model: transcription occurs while the user is logged in and participating in calls.

Separating runtime files from user data prevents upgrades from replacing configuration or transcripts.

Using a packaged Python runtime eliminates Python, uv and repository setup from the tester machine.

A thin controller preserves the current composition/lifecycle architecture while making the application operable by a nontechnical user.

CPU-first validation isolates installer and hardware-capture issues from NVIDIA/CUDA runtime issues.

`onedir` packaging favors transparent native-library deployment and diagnosability over the convenience of a self-extracting single executable.

## Consequences

Positive consequences include reproducible installation on a clean Windows machine, no development tooling on tester machines, straightforward remote diagnostics, preservation of user data across upgrades, graceful lifecycle control, and a clear separation between packaging/UI and the existing service core.

Negative consequences include a new Windows-specific distribution layer, additional build tooling, a small controller UI to maintain, a larger installer due to Python/ML/native dependencies, and the need to validate PyInstaller collection of native and package data.

NVIDIA GPU packaging remains additional work after CPU portability is established.

## Alternatives considered

**Require the tester to clone the repository and install Python/uv.**

Rejected because the tester is nontechnical and the developer cannot directly support the machine.

**Run the application as a Windows Service.**

Rejected for the current usage model because the application needs user-session audio/device behavior and user-controlled start/stop semantics. A background service also adds operational complexity without providing a current requirement.

**Ship a portable ZIP only.**

Rejected as the primary distribution because an installer can establish deterministic locations, shortcuts, upgrades and uninstall behavior with less work for the tester.

**Use PyInstaller `onefile`.**

Not selected initially. Self-extraction obscures native DLL layout and increases startup/debugging complexity. `onedir` is preferred while portability is still being validated.

**Introduce a full desktop application UI.**

Rejected for the first deployment. Only a thin operational controller is needed.

**Enable NVIDIA GPU support in the first installer.**

Rejected for the first portability test because it would combine two independent unknowns: packaging portability and CUDA/CTranslate2 deployment.

## Testing requirements

The packaged runtime must be tested without relying on the developer's virtual environment or globally installed Python modules.

Installer tests must verify fresh install, start, graceful stop, log creation, configuration loading, SQLite persistence, support-bundle generation, upgrade without data loss and uninstall behavior.

Real-hardware acceptance must verify both Windows audio sources and the same capture/executor health counters already used during development.

The first external acceptance is successful when the tester can install the application, run a conversation, stop it cleanly, generate a support bundle and send that bundle back without developer intervention.

## Documentation impact

`architecture.md` should describe the controller as an external runtime host around the existing `Application`.

`deployment.md` should document packaged Windows layout, CPU/NVIDIA runtime profiles and upgrade behavior.

`development.md` should document building the packaged runtime and installer.

`testing.md` should document installer and clean-machine acceptance.

`observability.md` should document the support bundle contents.
