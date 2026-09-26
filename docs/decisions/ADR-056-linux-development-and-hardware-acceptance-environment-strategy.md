# ADR-056 — Linux Development and Hardware Acceptance Environment Strategy

## Status

Accepted

## Context

- Audio Transcription Service is currently a Windows-first application with established CPU, NVIDIA and AMD Windows distributions.
- The next major milestone is Linux support.
- Linux development must not compromise the existing Windows development, packaging, testing, or release workflows.
- The application also has unusually strong operating-system integration requirements. In particular, Linux support will require validation of microphone capture, desktop/system-audio capture, Linux audio-server behavior, default-device selection, device changes, recovery after audio-device loss, GUI/controller behavior, packaging, and potentially GPU acceleration.
- Several environments are available on the existing Windows development laptop, including WSL2, containers, virtual machines, dual boot, and native Linux.
- These environments do not provide equivalent evidence for an audio application.
- WSL2 provides a real Linux kernel and is highly suitable for Linux development and automated application tests, but WSLg audio is remoted between Linux and the Windows host rather than exposing the same audio architecture used by a normal native Linux desktop.
- Containers add another isolation layer and therefore cannot establish compatibility with real Linux desktop audio hardware.
- Virtual machines are useful for isolated desktop and installation testing but expose virtualized or redirected audio devices rather than the laptop's normal native Linux hardware topology.
- Some project behavior must therefore be validated on Linux running directly on hardware.
- At the same time, Windows must remain readily available because existing Windows CPU, NVIDIA, and AMD distributions must continue to be reproducible and tested.

## Decision

1. Windows 11 remains the primary host OS and authoritative
   Windows build/test environment.

2. WSL2 is the primary Linux development environment.

3. Linux development uses a separate repository checkout
   stored inside the WSL filesystem.

4. WSL2 is authoritative for:
   - Linux unit tests
   - portable integration tests
   - linting/type checking
   - Linux dependency development
   - headless application behavior

5. WSL2 is NOT authoritative for:
   - microphone compatibility
   - system-audio capture
   - PipeWire/ALSA device behavior
   - device changes/recovery
   - Linux desktop integration
   - hardware-specific GPU behavior

6. Initial native-hardware investigation and acceptance testing
   will use an Ubuntu Live USB.

7. The Live USB is suitable for validating the native Linux
   audio/device architecture but is not considered the final
   persistent packaging/GPU acceptance environment.

8. A persistent native Linux installation will be introduced
   only when the implementation requires frequent native
   integration testing.

9. When that becomes necessary, preference order is:

   a. second internal SSD, if the laptop supports one;
   b. Windows/Linux dual boot on the existing internal SSD.

10. Windows will not be replaced as the primary operating system.

11. Docker and VMs may be introduced for specific build,
    CI, clean-install, or isolation requirements, but neither
    substitutes for native Linux hardware acceptance.

12. Before modifying the Windows disk or boot configuration,
    Windows data must be backed up and disk encryption recovery
    credentials verified.

## Rationale

- This strategy separates fast development feedback from authoritative hardware validation.
- WSL2 provides a low-friction Linux development environment while allowing the existing Windows workflow to remain operational.
- Native Linux is required because the application's most platform-sensitive behavior occurs at the desktop-audio and hardware boundaries.
- Using native Linux only for acceptance testing avoids making every development iteration require rebooting the laptop.
- Keeping independent Windows and Linux repository clones also reduces accidental coupling between platform-specific virtual environments, generated files, build artifacts, filesystem semantics, and packaging tools.
- Keeping Windows as the host protects the already-established Windows distribution workflow.
- An external native-Linux installation provides real Linux kernel, audio, device, and GPU behavior while avoiding unnecessary changes to the working Windows system disk.

## Consequences

### Positive

- no additional hardware is required to start Linux work;
- no partition changes are required yet;
- Windows builds remain protected;
- development remains fast through WSL2;
- real Linux audio can still be investigated immediately;
- we postpone irreversible/riskier setup until it provides concrete value.

### Negative

- Live USB sessions are ephemeral;
- repeated native testing requires rebooting;
- installing extra libraries in the Live environment is less convenient;
- GPU and final installer testing will eventually require a persistent Linux installation;
- two development environments must be understood and maintained.

## Alternatives Considered

- WSL2 only: insufficient evidence for native desktop audio.
- Docker only: insufficient for native desktop hardware.
- VM only: audio hardware remains virtualized/redirected.
- immediate internal dual boot: unnecessary risk before we know what Linux implementation requires.
- Linux as primary OS: would weaken the established Windows development/release environment.
- dedicated Linux machine: useful later, unnecessary now.

## Validation Strategy

- Linux unit tests and platform-independent integration tests should run successfully under WSL2.
- Existing Windows quality gates and packaging must continue to run independently on Windows.
- Any Linux functionality involving real audio hardware or desktop integration must be tested on the native Linux environment before being considered supported.
- Tests that intentionally exercise WSL-specific behavior must be identified as such and must not be used as substitutes for native Linux acceptance tests.
- Future CI may run platform-independent Linux tests in containers or hosted Linux runners, but real audio-device acceptance remains a hardware test.

## Follow-up Decisions

- A subsequent architecture discussion will define the initial supported Linux distribution and version matrix.
- Another decision will define the Linux audio stack assumptions and the application-owned Linux capture adapter, including PipeWire, PulseAudio compatibility, ALSA boundaries, system-audio capture, microphone selection, and device recovery.
- Linux packaging and GPU runtime support will be decided independently from basic Linux CPU compatibility.

## Related Decisions

- ADR-015 — Testing Philosophy
- ADR-016 — Application Composition Root
- ADR-018 — Audio Capture Architecture
- ADR-019 — Audio Capture Recovery
- ADR-020 — Audio Ownership Boundaries
- ADR-035 — Audio Capture Discontinuity Propagation and Processing State Reset
- ADR-039 — Multi-Source System and Microphone Audio Processing Architecture
- ADR-049 — Windows End-User Packaging, Runtime Layout, and Interactive Control Host
- ADR-050 — Interactive Controller and Transcription Runtime Process Boundary
- ADR-052 — Deterministic Distribution Metadata for Support Diagnostics