# ADR-038: Recover WASAPI Loopback Capture on Windows Default Output Device Changes

## Status
Accepted

## Context
The service captures system audio through a PyAudioWPatch WASAPI loopback stream resolved from the Windows default render device. Real-device testing showed that an open loopback stream is bound to the endpoint selected when the stream was created and does not automatically follow subsequent Windows default-output changes.

When Bluetooth headphones were the active endpoint and became unavailable, the PortAudio stream became inactive and callbacks stopped. When speakers remained available while Windows switched output to headphones, the old speaker loopback stream stayed active but continued targeting the old endpoint.

PyAudio/PortAudio device enumeration also proved unsuitable as a device-change detector. Device indexes are transient, and a long-lived PortAudio initialization does not reliably refresh its device enumeration when Windows audio endpoints change.

Windows Core Audio `IMMNotificationClient`, accessed through `pycaw`, reliably emitted default render endpoint change notifications. An experimental recovery sequence proved that handling the notification outside the COM callback, closing the old stream, fully terminating PyAudio, creating a fresh PyAudio instance, rediscovering the default WASAPI loopback, and reopening the stream successfully restored capture in both directions between speakers and Bluetooth headphones.

## Decision
Introduce a replaceable Windows audio-device monitor that observes Core Audio default-render endpoint changes.

The monitor will:

- listen for Windows Core Audio endpoint notifications;
- react to the default `eRender` / `eConsole` endpoint changing;
- keep the COM notification callback lightweight;
- communicate the change to the capture lifecycle through a thread-safe signal or queue;
- optionally carry the Windows endpoint ID for logging and diagnostics.

`PyAudioCapture` remains the owner of PyAudio and stream lifecycle.

When a default render-device change is received, capture will:

```text
stop/close current stream
        ↓
terminate current PyAudio
        ↓
signal downstream discontinuity
        ↓
create fresh PyAudio
        ↓
rediscover current default WASAPI loopback
        ↓
open new capture stream
        ↓
resume frame delivery
```

If the new default loopback cannot immediately be opened, capture will remain alive and reuse the existing capture recovery/retry policy.

PyAudio device indexes will not be treated as stable device identities. They are valid only within the current PortAudio device enumeration and are used only when opening the current stream.

The Windows Core Audio endpoint ID may be retained for observability but will not be mapped or persisted as a PyAudio index.

## Consequences**

### Positive consequences:

- Capture automatically follows the Windows default output device.
- No periodic device polling is required.
- No secondary process is required.
- Device indexes are not incorrectly treated as stable identities.
- Hardware-specific behavior remains behind the audio-capture boundary.
- Existing downstream discontinuity handling can be reused.
- PyAudioWPatch remains replaceable behind the existing abstraction.
- Recovery works even when the old stream remains active but is no longer the desired default endpoint.

### Negative consequences:

- The project gains a Windows-specific Core Audio dependency, likely `pycaw`.
- Capture lifecycle becomes somewhat more complex.
- COM callback/thread lifecycle must be managed carefully.
- A device change intentionally creates a short capture discontinuity.
- Reinitializing PortAudio is heavier than reopening only a stream, but occurs only on endpoint changes rather than continuously.

## Alternatives considered

**Poll `get_default_wasapi_loopback()` periodically**  
Rejected because a long-lived PortAudio device enumeration can become stale and because continual PyAudio recreation would be inefficient and unnecessary.

**Run a secondary monitoring process**  
Technically viable and experimentally motivated, but rejected because Windows Core Audio notifications provide an event-driven mechanism within the main process with less operational complexity.

**Keep the original loopback stream until it becomes inactive**  
Rejected because a stream may remain active on the old endpoint even after Windows changes the default output, meaning the service would capture the wrong device.

**Use PyAudio numeric device indexes as identities**  
Rejected because indices changed as devices appeared and disappeared during testing.

**Perform PyAudio recovery inside the Core Audio callback**  
Rejected because experimentation caused the process to hang. Native audio lifecycle work must occur outside the COM notification callback.

**Refresh PortAudio's WASAPI device list directly**  
Not selected because PyAudioWPatch does not expose a supported Python-level path that we can rely on, while the proven full reinitialization path works reliably.

**No automatic recovery**  
Rejected because changing output devices is normal desktop behavior and silently losing system-audio capture is unacceptable.

## Testing requirements

The implementation should cover:

- monitor emits one logical default-render change;
- capture ignores unrelated capture-device notifications;
- capture closes the current stream before terminating PyAudio;
- capture creates a fresh PyAudio instance after a change;
- capture rediscoveries the current default loopback rather than reusing an old index;
- downstream discontinuity is signaled on switch;
- capture resumes after successful recovery;
- temporary lack of a usable device keeps the service alive;
- repeated notifications do not cause overlapping recoveries;
- shutdown remains safe while recovery is pending or active.

## Operational observability

At minimum, log:

```text
default audio output changed
capture recovery started
old capture device
new capture device
capture recovery succeeded
capture recovery failed; retrying
```

with the Windows endpoint ID where useful.
