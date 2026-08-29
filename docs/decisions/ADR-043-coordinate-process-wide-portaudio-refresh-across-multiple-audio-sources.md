# ADR-043: Coordinate Process-Wide PortAudio Refresh Across Multiple Audio Sources

## Status

Accepted — implemented and validated on real Windows audio hardware.

## Context

The service operates two independent Windows capture paths:

```text
system_audio
microphone
```

ADR-039 established independent native capture ownership so device recovery in one source would not destroy the other source's active capture session. 

ADR-038 and ADR-040 both rely on recreating PyAudio/PortAudio state when the Windows default endpoint changes so the current default device can be rediscovered. 

Real-device testing later revealed that this assumption does not hold when two `PyAudio()` instances coexist in one process.

A controlled experiment produced:

```text
initial:
two PyAudio instances
default output = Headphones

Windows Settings:
Headphones → Speakers

terminate/recreate only system PyAudio
microphone PyAudio remains alive

result:
system PyAudio still reports Headphones
```

Without changing the Windows default again:

```text
terminate BOTH PyAudio instances
recreate BOTH PyAudio instances

result:
default output = Speakers
```

Therefore recreating one Python `PyAudio` wrapper does not provide a genuinely refreshed PortAudio default-device view while another PortAudio user remains alive.

The process-wide native PortAudio lifecycle must reach a fully terminated state before device/default enumeration is reliably refreshed.

## Decision

Windows default-device changes that require rediscovery of the active PortAudio/WASAPI defaults will trigger a **process-wide coordinated PortAudio refresh**.

Source capture resources remain source-owned during normal operation.

The ownership model becomes:

```text
Source-local ownership:
- capture stream
- capture queue
- selected default-device provider
- recovery state
- discontinuity signaling

Process-wide coordination:
- PortAudio refresh following Windows default-device changes
```

A single application-owned coordinator will serialize and coalesce native refresh requests from all capture sources.

The coordinated default-device recovery sequence is:

```text
default endpoint change detected
        ↓
coalesce concurrent/duplicate refresh requests
        ↓
close all active native streams
        ↓
terminate all PyAudio instances
        ↓
wait for Windows/device notifications to settle
        ↓
create fresh PyAudio sessions
        ↓
each source independently rediscover its current default device
        ↓
reopen each source stream
        ↓
resume source-local capture
```

The coordinator will not:

- persist device indexes;
- compare old and new friendly names;
- map Core Audio endpoint IDs to PortAudio indexes;
- decide which concrete input/output device should be used.

Each source retains its existing default-device policy:

```text
system_audio
→ current Windows default render loopback

microphone
→ current WASAPI defaultInputDevice
```

Core Audio notifications remain the authoritative signal that the selected Windows default changed.

The refresh coordinator owns only the cross-source native lifecycle operation.

After the common teardown/reinitialization boundary, source recovery becomes independent again.

If one source cannot reopen its current default:

```text
other source may resume successfully

failed source remains in its own recovery loop
```

A temporarily unavailable microphone therefore must not indefinitely prevent system-audio capture from resuming, and vice versa.

Duplicate or near-simultaneous render/capture default-device notifications must be coalesced so one Windows transition does not cause repeated full PortAudio restarts.

## Rationale

The experiments establish that PortAudio refresh semantics are effectively process-wide when multiple `PyAudio()` wrappers are active.

Keeping independent source streams remains desirable, but pretending that their underlying PortAudio enumeration lifecycle is fully independent causes stale default-device selection.

The coordinator makes the actual native constraint explicit while preserving source-local processing ownership everywhere else.

## Consequences

Positive:

- Settings-based default-device switching works reliably with both sources active.
- No stale-device knowledge is introduced.
- Device indexes remain transient.
- Existing source-specific default-selection policies remain unchanged.
- Duplicate Core Audio notifications can be coalesced at the correct lifecycle boundary.
- Downstream source processing remains isolated.
- A source that cannot reopen does not permanently block the other source.

Negative:

- A default-device change on one source briefly interrupts both native captures.
- Both source processing paths receive discontinuities during a coordinated PortAudio refresh.
- Native lifecycle coordination becomes more complex.
- The application gains a process-wide audio-infrastructure component.
- Windows device switches create slightly larger capture gaps than strictly source-local recovery would.

## Alternatives considered

**Continue recreating only the affected `PyAudio()` instance**

Rejected.

The controlled two-instance experiment demonstrated that device/default enumeration remains stale while another PyAudio instance remains alive.

**Track the previously selected device and reject it after a change**

Rejected.

The application should select the current Windows default, not reason about which previous device is stale.

**Map Core Audio endpoint IDs directly to PortAudio devices**

Rejected.

It introduces additional identity mapping that is unnecessary when a full PortAudio refresh reliably restores correct default discovery.

**Use one shared PyAudio wrapper for both streams**

Not selected automatically.

It could simplify native lifecycle ownership, but would also substantially change existing stream ownership and failure boundaries. The observed requirement is coordinated refresh, not necessarily shared stream/session ownership.

**Put system and microphone capture in separate processes**

Rejected for now.

Separate processes would provide genuinely separate PortAudio runtimes but introduce unnecessary IPC, deployment, lifecycle, and observability complexity.

## Testing requirements

- A default change request tears down all current PyAudio sessions before any recreation.
- Recreation occurs only after full teardown.
- Concurrent render and capture notifications are coalesced.
- Duplicate notifications do not cause repeated complete refreshes.
- Both sources independently rediscover their current defaults.
- System-audio recovery uses the current default loopback.
- Microphone recovery uses WASAPI `defaultInputDevice`.
- Failure reopening one source does not permanently prevent the other from resuming.
- Both source-local processing paths receive discontinuity notification when their native capture is refreshed.
- Shared conversation timestamps continue without reset.
- Shutdown remains safe during pending or active coordinated refresh.
- Real-device validation covers:
  - Headphones → Speakers through Settings;
  - Speakers → Headphones through Settings;
  - Headset → Microphone Array through Settings;
  - Microphone Array → Headset through Settings;
  - physical disconnect and reconnect;
  - startup with one unavailable source.

## Implementation validation

ADR-043 has been implemented and validated with automated tests and real
Windows audio hardware.

The implementation introduces one application-owned
`PortAudioRefreshCoordinator` shared by the system-audio and microphone
capture paths.

Normal native resource ownership remains source-local:

```text
system_audio capture
    ├── stream
    ├── PyAudio session
    ├── device provider
    └── recovery state

microphone capture
    ├── stream
    ├── PyAudio session
    ├── device provider
    └── recovery state
```

Windows default-device changes use the coordinated process-wide boundary:

```text
Core Audio default-device notification
        ↓
signal shared refresh generation
        ↓
coalesce duplicate / near-simultaneous notifications
        ↓
mark both captures as participating in coordinated refresh
        ↓
close both native streams
        ↓
terminate both PyAudio sessions
        ↓
wait for the notification burst to settle
        ↓
recreate fresh source-owned PyAudio sessions
        ↓
system_audio resolves current default WASAPI loopback
microphone resolves current WASAPI defaultInputDevice
        ↓
reopen independently
        ↓
resume capture
```

The refresh-request generation is signaled immediately when the matching
Core Audio notification reaches the capture lifecycle.

This is intentionally separate from execution of the asynchronous coordinated
refresh.

The separation ensures that additional notifications arriving while a capture
is already awaiting refresh still advance the shared generation and extend the
same logical refresh rather than creating another full PortAudio restart.

The notification settle window was validated against real physical-device
transitions where Windows emitted several render and capture endpoint changes
for one hardware action.

Source-local recovery is suspended while a capture is participating in the
coordinated refresh.

This preserves the required invariant:

> no source may recreate a PyAudio session while the coordinator is waiting
> for PortAudio to reach and remain in the fully terminated state.

After coordinated restore completes, or if restoration of that source fails
with an expected device-availability error, normal source-local recovery
becomes active again.

### Recoverable unavailable source

Startup with no usable microphone was validated.

PyAudioWPatch reports the missing WASAPI default input as:

```text
OSError(-9996, "Invalid device info")
```

This is treated as an expected device-availability condition rather than an
application startup failure.

The validated behavior is:

```text
system_audio available
        ↓
system capture runs

microphone unavailable
        ↓
microphone pipeline remains alive
        ↓
bounded exponential recovery retry
        ↓
application remains running
```

When a usable microphone later appears, the Core Audio notification interrupts
the ordinary recovery backoff immediately and causes coordinated PortAudio
refresh.

The microphone then joins the existing conversation without restarting the
application or resetting the shared conversation timeline.

### Microphone default discovery

Microphone discovery now uses the WASAPI-specific default:

```python
get_default_wasapi_device(d_in=True)
```

rather than PortAudio's generic default-input lookup.

The returned device must expose at least one input channel.

This was validated with:

```text
Headset (Razer Barracuda X (BT))
Microphone Array (Realtek(R) Audio)
```

and correctly followed the Windows `eCapture/eConsole` default in both
directions.

### Real-device validation

The coordinated lifecycle was validated on Windows with both capture sources
running.

Successful scenarios:

```text
Windows Settings:
Headphones → Speakers
Speakers → Headphones

Windows Settings:
Headset → Microphone Array
Microphone Array → Headset

Physical device:
disconnect
reconnect

Startup:
microphone unavailable
microphone later becomes available
```

Observed native formats changed correctly with the selected endpoints,
including:

```text
Bluetooth output:
44.1 kHz stereo

Realtek output:
48 kHz stereo

Razer microphone:
16 kHz mono

Realtek microphone:
48 kHz stereo
```

Physical disconnect/reconnect produced bursts of Core Audio notifications.

Those bursts were successfully coalesced into one process-wide refresh.

For example:

```text
refresh started generation=6
additional notifications arrive
refresh completed generation=9
```

and:

```text
refresh started generation=11
refresh completed generation=11
```

No immediate second full refresh followed the same physical transition.

Both capture paths resumed against the correct current defaults.

Both source processing paths received discontinuity notifications.

Capture transport remained healthy:

```text
system_audio frames_dropped=0
microphone frames_dropped=0
```

Application shutdown remained clean after repeated refresh operations.

### Automated verification

The completed implementation was verified with:

```text
pytest:
402 passed

mypy:
Success: no issues found in 103 source files

ruff:
All checks passed
```

The test coverage includes:

- all participants disposed before any participant is recreated;
- notification settling occurs only after full teardown;
- duplicate notifications extend one logical refresh;
- same-source notifications arriving while refresh is already running are
  included in the shared generation;
- one participant restore failure does not prevent restoration attempts for
  other participants;
- unexpected restoration failures remain visible;
- default-device notifications delegate to process-wide coordination;
- ordinary inactive-stream recovery remains source-local;
- startup device-discovery `OSError` enters recovery instead of failing the
  service;
- recovery backoff is interrupted immediately by a default-device
  notification;
- source-local recovery cannot recreate PortAudio during an active coordinated
  refresh;
- failed coordinated restoration re-enables source-local recovery;
- both production capture paths share the same coordinator through the
  composition root.

## Superseded aspects of earlier decisions

ADR-039 and ADR-040 correctly established independent source-owned capture
resources and source-local recovery.

ADR-043 refines one specific assumption from those decisions.

For ordinary capture failures:

```text
system failure → system-local recovery
microphone failure → microphone-local recovery
```

remains valid.

For Windows default-device changes requiring refreshed PortAudio enumeration:

```text
render or capture default changes
        ↓
process-wide native PortAudio refresh
```

is authoritative.

This refinement is necessary because real-device experimentation demonstrated
that PortAudio's default-device enumeration remains effectively process-wide
while any PyAudio instance remains alive.

## Related decisions

- ADR-035 — Audio Capture Discontinuity Propagation and Processing-State Reset
- ADR-038 — Recover WASAPI Loopback Capture on Windows Default Output Device Changes
- ADR-039 — Multi-Source System and Microphone Audio Processing Architecture
- ADR-040 — Follow and Recover the Windows Default Microphone Input Device
