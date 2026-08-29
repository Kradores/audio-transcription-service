# ADR-040: Follow and Recover the Windows Default Microphone Input Device

- **Status:** Accepted
- **Date:** 2026-08-20

## Context

ADR-039 establishes that the service will capture system audio and microphone audio through independent real-time processing paths.

The microphone capture path must determine which Windows input device to capture from and must remain operational when that device changes, disappears, or becomes temporarily unavailable.

The intended service behavior is configuration-free for the normal case: the microphone selected by Windows should be the microphone captured by the service.

Windows Core Audio distinguishes default endpoints by both data flow and role.

For microphone capture the relevant flow is:

```text
eCapture
```

Windows exposes multiple roles, including:

```text
eConsole
eMultimedia
eCommunications
```

`eCommunications` initially appeared to be the most semantically appropriate choice because the primary use case is capturing both sides of voice and video calls.

However, the service uses PyAudioWPatch/PortAudio to open WASAPI devices. The relationship between PortAudio's WASAPI `defaultInputDevice` and the Windows Core Audio endpoint roles therefore had to be verified rather than assumed.

The microphone capture design must also preserve the recovery principles already established for system-audio capture:

- device availability problems must not crash the service;
- default-device changes must be detected even when the old stream remains active;
- recovery must refresh native audio state rather than trust stale PortAudio enumeration;
- transient PortAudio device indexes must not be treated as stable device identity;
- device-monitor callbacks must remain lightweight;
- a microphone discontinuity must affect only the microphone processing path;
- system-audio capture must continue independently while microphone capture recovers.

## Experiment

A real-device experiment was performed on the target Windows environment using two available microphone endpoints:

```text
Headset (Razer Barracuda X (BT))
Microphone Array (Realtek(R) Audio)
```

The experiment compared:

1. Windows Core Audio defaults for `eCapture/eConsole`, `eCapture/eMultimedia`, and `eCapture/eCommunications`;
2. Core Audio default-device change notifications;
3. the WASAPI `defaultInputDevice` reported by a freshly created PyAudioWPatch instance.

### Initial state

Initially all three Windows capture roles pointed to the Razer headset:

```text
eConsole        → Razer
eMultimedia     → Razer
eCommunications → Razer
```

A fresh PyAudioWPatch instance reported:

```text
WASAPI defaultInputDevice → Razer
```

### Experiment 1 — Change only Default Communications Device

Using `mmsys.cpl` → Recording, only the Windows **Default Communications Device** was changed to the Realtek microphone.

Core Audio emitted:

```text
flow=eCapture
role=eCommunications
```

After the change, Windows reported:

```text
eConsole        → Razer
eMultimedia     → Razer
eCommunications → Realtek
```

A freshly created PyAudioWPatch instance still reported:

```text
WASAPI defaultInputDevice → Razer
```

Therefore changing only `eCommunications` did not change the WASAPI default input resolved by PyAudioWPatch/PortAudio.

### Experiment 2 — Change the normal Windows input device

The input device was then changed through Windows **System → Sound**.

Core Audio emitted changes for:

```text
eCapture/eConsole
eCapture/eMultimedia
```

After the change, Windows reported:

```text
eConsole        → Realtek
eMultimedia     → Realtek
eCommunications → Razer
```

A freshly created PyAudioWPatch instance reported:

```text
WASAPI defaultInputDevice → Realtek
```

Therefore the WASAPI `defaultInputDevice` exposed by PyAudioWPatch/PortAudio followed the normal Windows capture default rather than the communications-role endpoint.

### Experiment conclusion

On the target runtime:

```text
PyAudioWPatch WASAPI defaultInputDevice
            ↓
follows normal Windows capture default
            ↓
eCapture/eConsole
```

It does not follow a change made only to:

```text
eCapture/eCommunications
```

Following the communications endpoint would therefore require an additional mapping from Windows Core Audio endpoint identity to a PortAudio/WASAPI device.

The current PyAudioWPatch-facing device information does not provide a sufficiently direct stable endpoint-ID mapping for this to be preferable to following the normal default device.

## Decision

Microphone capture will follow the **normal Windows default input device**.

The authoritative Core Audio endpoint selection for microphone monitoring is:

```text
flow = eCapture
role = eConsole
```

The initial implementation will not follow the Windows Default Communications Device.

This choice deliberately aligns the Core Audio change signal with the WASAPI default input that PyAudioWPatch/PortAudio can resolve reliably.

## Device discovery

Microphone capture will discover the current input device from a fresh PyAudioWPatch instance using the WASAPI host API's:

```text
defaultInputDevice
```

The resulting PortAudio device index is transient and is used only to open the current native stream.

A PortAudio device index must not be persisted or treated as stable device identity.

Device discovery remains behind an application-owned abstraction so the underlying capture implementation can be replaced later.

## Default-device monitoring

Windows default-device changes will be detected using Core Audio endpoint notifications.

The microphone monitor will react only to:

```text
eCapture / eConsole
```

Notifications for:

```text
eCapture / eMultimedia
eCapture / eCommunications
```

will not independently trigger microphone recovery.

Windows may update `eConsole` and `eMultimedia` together for a single user action. Reacting only to the selected authoritative role prevents duplicate recovery for the same logical device change.

Render-device notifications are unrelated to microphone capture and are ignored by the microphone monitor.

## Device-monitor design

The Windows device-monitor implementation should support selecting the flow and role it observes rather than embedding output-specific or microphone-specific behavior.

Conceptually:

```text
system-audio monitor
    flow = eRender
    role = eConsole

microphone monitor
    flow = eCapture
    role = eConsole
```

Each capture path receives its own monitor instance.

The exact configuration types and enum representation are implementation details.

## Lightweight notification callbacks

Core Audio notification callbacks must remain lightweight.

A callback may:

- inspect notification metadata;
- determine whether flow and role match the configured endpoint policy;
- signal that recovery is required;
- enqueue lightweight notification information;
- return.

A callback must not perform capture recovery, PyAudio recreation, expensive device discovery, or other blocking work.

The experiment reinforced this boundary: performing Core Audio inspection from notification/worker threads requires explicit COM lifecycle management.

Any thread that directly performs COM operations must own the required COM initialization and cleanup.

## Recovery triggers

Microphone recovery may be triggered by either:

1. the current microphone stream becoming unavailable or unusable; or
2. a matching `eCapture/eConsole` default-device change notification.

The second trigger is necessary even if the current stream remains active.

For example:

```text
Laptop microphone remains connected
        │
        │ user selects headset microphone
        ▼
old stream may still be active
```

Stream-health monitoring alone would therefore allow the service to continue recording the wrong microphone indefinitely.

## Recovery lifecycle

When recovery is required, microphone capture will conceptually perform:

```text
detect microphone change or failure
              ↓
close current microphone stream
              ↓
terminate microphone-owned PyAudio instance
              ↓
signal microphone capture discontinuity
              ↓
create fresh PyAudio instance
              ↓
resolve current WASAPI defaultInputDevice
              ↓
open new microphone stream
              ↓
resume capture
```

A fresh PyAudio instance is required so recovery does not rely on potentially stale PortAudio device enumeration.

The microphone capture path owns its native audio resources independently from system-audio capture, as established by ADR-039.

Microphone recovery must therefore not recreate or terminate the system-audio capture session.

## Capture discontinuity

A microphone device change or loss represents a discontinuity in the microphone audio stream.

The discontinuity resets only the stateful microphone processing components:

```text
microphone AudioNormalizer
microphone AudioVad
microphone SpeechSegmentAssembler
```

The system-audio processing path remains untouched.

The microphone's timestamps must continue on the shared conversation timeline established by ADR-039 and must not restart from zero after recovery.

Losing several seconds of microphone audio during genuine Windows device switching and recovery is acceptable. Correct stream boundaries and reliable recovery are preferred over attempting to fabricate continuity across a hardware transition.

## Missing microphone at startup

Absence of a usable microphone is an expected recoverable hardware condition.

It must not terminate the entire service.

Conceptually:

```text
application starts
        │
        ├── system audio available
        │       ↓
        │     running
        │
        └── microphone unavailable
                ↓
            recovery state
                ↓
          retry indefinitely
```

When a usable Windows default microphone later becomes available, microphone capture should open it and join the ongoing conversation session.

System-audio capture continues while the microphone is unavailable.

## Microphone loss while running

If the active microphone disappears or becomes unusable:

```text
microphone failure
        ↓
close/release microphone capture
        ↓
signal microphone discontinuity
        ↓
enter recovery
        ↓
retry device discovery
```

The system-audio pipeline continues independently.

When a usable default microphone becomes available, microphone capture resumes against the current Windows default input.

## Error handling

Expected device availability and stream-loss conditions are recoverable.

Unexpected programming or processing failures must not be silently converted into permanent recovery loops.

The implementation must preserve the distinction between:

```text
expected device/hardware condition
        → recover

unexpected application failure
        → surface failure
```

This follows the existing reliability model for audio capture.

## Observability

Microphone device behavior must be observable through structured logs and metrics where appropriate.

Important events include:

- microphone capture startup;
- selected WASAPI input device;
- native device format;
- default-input change detected;
- microphone stream unavailable;
- recovery started;
- recovery attempt failed;
- recovery succeeded;
- microphone discontinuity signaled;
- frames dropped during transport;
- microphone capture shutdown.

Device indexes may be logged diagnostically but must not be interpreted as stable identity.

Where available, human-readable device names may also be logged for diagnostics.

## Microphone privacy and access

Windows microphone privacy settings may prevent desktop applications from accessing the microphone.

The service will not attempt to modify Windows privacy or permission settings.

Microphone-open failures must be observable so the user can diagnose access problems.

Where the underlying APIs provide enough information to distinguish access denial from device absence, that distinction should be preserved in diagnostics.

## Configuration

The initial implementation will not expose configurable microphone-selection roles.

The supported automatic policy is:

```text
Windows default input
→ eCapture/eConsole
```

Introducing configuration with only one supported behavior would add unnecessary surface area.

Configuration becomes justified when multiple real policies are supported, such as:

```text
default
explicit device
```

or other future selection strategies.

## Explicit microphone selection

Explicit microphone selection is outside the scope of this decision.

A future implementation may allow the user to select a specific microphone independently from the Windows default.

That feature would require additional decisions concerning:

- stable device identity;
- disappearance and reconnection;
- fallback behavior;
- configuration representation;
- whether Windows default-device changes are ignored while explicit selection is active.

Those requirements will be addressed if explicit selection becomes necessary.

## Default Communications Device

Following the Windows Default Communications Device is deliberately not implemented initially.

This option was considered because it is semantically attractive for call transcription.

It was rejected for the initial implementation because real-device testing demonstrated that changing only `eCapture/eCommunications` does not change the WASAPI `defaultInputDevice` exposed by PyAudioWPatch/PortAudio.

Supporting it would therefore require an additional Windows-specific endpoint mapping mechanism.

The additional complexity is not justified while the normal Windows default microphone provides a simple, observable, and experimentally validated selection path.

This decision may be revisited if following the communications endpoint becomes an explicit requirement.

## Alternatives considered

### Follow `eCapture/eCommunications`

Rejected for the initial implementation.

It aligns conceptually with communication workloads, but real-device testing demonstrated that PyAudioWPatch's WASAPI `defaultInputDevice` does not follow changes made only to the communications-role endpoint.

Implementing this policy reliably would require additional Core Audio-to-PortAudio endpoint mapping.

### Match Core Audio and PortAudio devices by friendly name

Rejected.

Friendly names are useful for diagnostics but are not sufficiently strong device identity for a reliability-focused capture architecture.

Names may not be unique and should not become the foundation of native-device selection.

### Poll PortAudio for device changes

Rejected.

Windows Core Audio already provides event-driven default-endpoint notifications.

Polling would introduce unnecessary timing, stale-enumeration, and identity problems.

### Detect only stream failure

Rejected.

Changing the Windows default microphone does not necessarily invalidate the existing stream.

The service could therefore continue capturing an old microphone indefinitely after the user selected another one.

### React to both `eConsole` and `eMultimedia`

Rejected initially.

Windows commonly changes both roles during one user action. Reacting independently to both can cause duplicate recovery.

`eConsole` is the authoritative role for the initial microphone-selection policy.

## Consequences

### Positive

- Microphone selection follows the normal Windows input selected by the user.
- The behavior has been validated experimentally on the target environment.
- Device changes can be detected without polling.
- PyAudioWPatch can resolve the selected device directly through its WASAPI default input.
- No fragile Core Audio-to-PortAudio friendly-name mapping is required.
- Device recovery follows the same proven philosophy as system-output recovery.
- Microphone failures remain isolated from system-audio capture.
- The design remains simple and replaceable.
- Native device indexes remain transient implementation details.

### Negative

- The service does not initially follow a separately configured Windows Default Communications Device.
- Applications that explicitly use a microphone different from the normal Windows default may not match the microphone captured by the service.
- Explicit microphone selection is not initially supported.
- Native capture recovery requires destroying and recreating the microphone PyAudio session.

### Risks

- Some communication applications may use application-specific microphone routing that differs from the Windows normal default.
- Windows or PortAudio behavior may differ across hardware or driver combinations.
- Bluetooth devices may expose changing formats or availability during profile transitions.
- Microphone privacy settings may prevent capture.
- Device recovery necessarily creates a temporary gap in microphone audio.

These risks will be handled through observability and real-device validation rather than speculative complexity.

## Follow-up work

Implementation following this ADR should proceed incrementally:

1. Generalize the Windows audio-device monitor so flow and role are selectable.
2. Add tests for exact flow/role filtering.
3. Introduce microphone WASAPI device discovery using a fresh PyAudio instance and `defaultInputDevice`.
4. Implement microphone native capture behind the existing `AudioCapture` abstraction where appropriate.
5. Implement microphone device-loss and default-change recovery.
6. Connect microphone recovery to source-local discontinuity handling.
7. Integrate microphone capture into the ADR-039 multi-source orchestration.
8. Add microphone-specific structured logging and metrics.
9. Validate normal-default switching in both directions on real hardware.
10. Validate microphone removal and reconnection.
11. Validate startup with no usable microphone.
12. Validate simultaneous system-audio and microphone capture.
13. Run a real two-person call and verify both sides are persisted with correct source identity and comparable timestamps.

## Related decisions

- ADR-043: Coordinate Process-Wide PortAudio Refresh Across Multiple Audio Sources