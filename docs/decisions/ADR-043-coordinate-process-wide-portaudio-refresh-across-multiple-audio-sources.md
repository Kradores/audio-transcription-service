# ADR-043: Coordinate Process-Wide PortAudio Refresh Across Multiple Audio Sources

### Status
Accepted

### Context

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

### Decision

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

### Rationale

The experiments establish that PortAudio refresh semantics are effectively process-wide when multiple `PyAudio()` wrappers are active.

Keeping independent source streams remains desirable, but pretending that their underlying PortAudio enumeration lifecycle is fully independent causes stale default-device selection.

The coordinator makes the actual native constraint explicit while preserving source-local processing ownership everywhere else.

### Consequences

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

### Alternatives considered

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

### Testing requirements

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
