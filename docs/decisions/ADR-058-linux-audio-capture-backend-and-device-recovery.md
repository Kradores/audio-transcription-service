# ADR-058: Linux Audio Capture Backend and Device-Recovery Strategy

## Status

Accepted

## Date

2026-09-28

## Context

Audio Transcription Service currently supports Windows audio capture through a Windows-specific WASAPI/PyAudioWPatch implementation. ADR-057 established platform-specific ownership so Linux audio support can be introduced without changing or weakening the existing Windows backend.

The shared application already depends on the `AudioCapture` abstraction. Capture implementations provide lifecycle control, asynchronously expose `AudioFrame` values, and notify the pipeline when capture continuity is lost.

Native Ubuntu reconnaissance was performed before choosing a Linux backend.

The tested environment used Ubuntu 26.04.1 with PipeWire 1.6.2, WirePlumber 1.6.2, ALSA hardware devices, and Bluetooth audio.

Native testing established that PipeWire and WirePlumber provide the required desktop-audio behavior:

| Requirement | Native result |
| --- | --- |
| Default microphone capture | Working |
| Bluetooth microphone capture | Working |
| System-output capture | Working through sink capture |
| Default source/sink changes | Event-driven and observable |
| Automatic fallback when Bluetooth disappears | Working |
| Automatic return to Bluetooth when available and selected | Working when the Bluetooth profile/source is available |
| Long-lived microphone stream across default changes | Working |
| Long-lived system-output stream across default changes | Working |
| Stable numeric node/object IDs | Not available |
| Stable semantic node names | Observed across reconnects |
| Capture-side timestamps | Available through PipeWire |
| Python 3.14 native integration | Validated with CFFI |

A feasibility spike then tested direct native PipeWire integration through a small C layer exposed to Python using CFFI out-of-line/API mode.

The same native bridge:

- compiled and imported successfully under Python 3.14;
- linked against `libpipewire-0.3`;
- created and destroyed `pw_thread_loop`, `pw_context`, and `pw_core` resources correctly;
- returned a clean `EHOSTDOWN` error when no PipeWire server existed in WSL;
- connected successfully on native Ubuntu;
- captured real microphone PCM;
- captured real system-output PCM using sink capture;
- survived default microphone changes without stream recreation;
- survived default output changes without stream recreation;
- exposed native capture timing without invoking Python from PipeWire's realtime processing callback.

The microphone recovery test preserved an approximately 2.09-second real capture gap while Bluetooth disappeared and returned.

The controlled system-output migration test preserved an approximately 103 ms capture gap while the default sink changed from Bluetooth to internal speakers and back.

`pw_buffer.time` preserved these real capture-time gaps.

`pw_stream_get_time_n()` succeeded on every measured buffer, and graph ticks remained monotonic, but graph ticks alone did not represent the physical Bluetooth outage. Therefore graph ticks are useful diagnostic information but are not sufficient as the application's capture timestamp.

`SPA_META_Header` was requested during the spike but was not supplied on the tested audio paths. Linux capture must therefore not depend on this optional metadata.

Bluetooth profile/source availability was also observed to be imperfect during fresh Live USB sessions. PipeWire/WirePlumber can migrate an existing stream when a usable default becomes available, but the application must not assume that a particular Bluetooth source will always become available successfully.

## Decision

Linux audio capture will use the **native PipeWire C API through a small project-owned C shim exposed to Python with CFFI out-of-line/API mode**.

The implementation will live entirely under the Linux platform boundary and will implement the existing shared `AudioCapture` contracts.

The Linux backend will not use PyAudio/PortAudio, direct ALSA capture, the PulseAudio compatibility API, GStreamer, or `pw-record` as its production capture mechanism.

`pw-record` may remain useful as an external diagnostic/reference tool during native acceptance testing.

### Native ownership

The C shim will own PipeWire-native resources including:

```text
pw_thread_loop
pw_context
pw_core
pw_stream
native capture buffers
native timing data
```

Python will not own or manipulate raw PipeWire objects.

The public C boundary should remain intentionally small and replaceable, conceptually exposing operations such as:

```text
create
start
read
stop
destroy
```

Exact function names and data structures are implementation details and are not fixed by this ADR.

### Realtime boundary

PipeWire realtime processing callbacks must remain entirely native.

The realtime callback must not:

```text
invoke Python
acquire the Python GIL
construct NumPy objects
perform application logging
perform blocking I/O
execute application/business logic
perform unbounded allocation
```

Its responsibility is limited to obtaining the PipeWire buffer, copying the required PCM and timing information into bounded native storage, returning the PipeWire buffer, and exiting quickly.

Python will consume captured records outside the PipeWire realtime thread.

### Native buffering

A bounded native queue or ring buffer will separate PipeWire's realtime processing thread from Python consumption.

Overflow behavior must be deterministic and observable.

The production implementation must expose dropped-buffer/frame information through structured diagnostics rather than blocking the PipeWire realtime thread.

The precise ring-buffer implementation and synchronization primitives are coding details and may be selected during implementation.

### Microphone capture

The microphone capture stream will use PipeWire default-target policy rather than binding permanently to a runtime numeric node ID.

WirePlumber will remain responsible for desktop default-device policy and normal target relinking.

When the default microphone changes and PipeWire/WirePlumber can migrate the stream, Audio Transcription Service will allow that migration to happen without destroying and recreating the stream.

### System-output capture

System audio will use a native PipeWire capture stream configured for sink capture using:

```text
stream.capture.sink = true
```

The stream will follow the default output according to PipeWire/WirePlumber policy.

The application will not locate and permanently bind itself to transient monitor-node IDs when default-following behavior is requested.

### Device identity

PipeWire numeric object IDs and object serials are runtime handles and must not be treated as persistent device identity.

Native tests demonstrated that numeric IDs change as Bluetooth devices disappear and return.

Where device identity or diagnostics are needed, semantic properties such as node/device names and relevant backend properties may be recorded.

Persisted configuration must not rely on runtime PipeWire object IDs.

The initial Linux product behavior remains default-device oriented. A richer user-selectable persistent-device model may be designed separately if required later.

### Timestamping

`pw_buffer.time` will be the primary native capture-time source.

The Linux capture implementation will map this native PipeWire time into the existing shared `AudioTimeline` used by the application's capture pipeline.

Timestamping must preserve real gaps in captured audio rather than pretending buffers remained continuous while a target was unavailable or being relinked.

`pw_stream_get_time_n()` may additionally be used for diagnostics and validation of graph timing.

Graph `ticks` must not by themselves be used as the authoritative application capture timestamp because native testing demonstrated a physical capture outage while graph ticks continued monotonically.

### Discontinuity handling

Linux will continue to use the existing shared discontinuity contract.

A normal WirePlumber target migration does not automatically require recreating the PipeWire stream.

A capture discontinuity must be reported when continuity of actual captured audio is lost in a way that requires downstream state to reset.

Detection may use native capture timestamps, stream state/error transitions, native queue overflow information, and other concrete PipeWire signals.

`SPA_META_HEADER_FLAG_DISCONT` is not required because `SPA_META_Header` was not available on the tested audio paths.

Thresholds used to distinguish ordinary PipeWire scheduling jitter from a meaningful capture gap must be derived from the negotiated stream format/timing and tested behavior rather than from a fixed assumption that every callback equals one processing frame.

The native tests demonstrated ordinary callback gaps of approximately 43–51 ms and migration gaps ranging from approximately 103 ms for controlled sink changes to approximately 2.09 seconds for a physical Bluetooth microphone disconnect/reconnect.

### Recovery responsibility

WirePlumber owns ordinary desktop routing policy and default-target relinking.

Audio Transcription Service will not reproduce Windows-style device orchestration on Linux when PipeWire/WirePlumber already provides the behavior.

The Linux backend remains responsible for failures outside normal target migration, including:

```text
PipeWire server unavailable
PipeWire server restart/disconnect
core connection failure
stream creation/connect failure
stream error or unexpected termination
native transport failure
bounded-buffer overflow
shutdown and restart
```

Recovery must remain local to the Linux capture implementation and must not introduce Linux-specific conditionals into shared application code.

### Bluetooth behavior

The application will not attempt to manage GNOME Settings or directly force Bluetooth profile selection as part of normal capture.

Bluetooth hardware/profile availability can fail independently of the PipeWire stream.

When a Bluetooth device is unavailable, the service should follow the usable OS default selected by WirePlumber.

Device/default transitions and prolonged absence of a usable target must be visible through structured logging and diagnostics.

### Python/native integration

CFFI out-of-line/API mode will be used to compile the project-owned native shim into a Python extension.

The production application will consume the compiled extension rather than compiling native code when the application starts.

Build-time requirements include a C compiler, Python development headers, PipeWire development headers, and CFFI build tooling.

End-user runtime installation must not require a compiler or Python development headers.

The packaged extension will dynamically use the platform's supported PipeWire runtime rather than bundling and running a competing desktop PipeWire server.

### Platform boundary

Linux-specific implementation belongs under:

```text
app/platforms/linux/
```

and associated Linux-owned native/build sources.

Shared normalization, VAD, segmentation, transcription, persistence, and application orchestration remain platform-independent.

Windows WASAPI/PyAudioWPatch behavior remains unchanged.

## Alternatives considered

| Alternative | Decision |
| --- | --- |
| Native PipeWire C shim + CFFI | Chosen |
| PulseAudio API through `pipewire-pulse` | Rejected as primary backend because it adds a compatibility layer and exposes less native timing/control |
| Direct ALSA | Rejected because desktop routing, Bluetooth policy, default-device following and system-output capture are provided above ALSA |
| GStreamer `pipewiresrc` | Rejected because it introduces a substantially larger runtime/integration surface for simple PCM capture |
| PortAudio/PyAudio | Rejected for Linux because it would hide or complicate the native PipeWire/WirePlumber behavior validated during reconnaissance |
| `pw-record` subprocess | Rejected for production because process/stdout transport provides weaker native timing/lifecycle integration; retained as a diagnostic oracle |
| Third-party Python PipeWire wrappers | Rejected because none evaluated provided the required mature streaming, timing, lifecycle and Python 3.14 characteristics |
| Direct CFFI callback into Python from PipeWire process callback | Rejected because Python execution must not occur on the realtime audio thread |

## Consequences

The Linux backend gains direct access to the desktop audio system actually responsible for routing, Bluetooth, default devices and system-output capture.

Normal device switching is simpler than the Windows implementation because WirePlumber can migrate existing streams automatically.

Capture timestamps can preserve actual outages and target-switch gaps rather than reconstructing continuity from Python callback arrival time.

The project gains a small native C component and therefore a native Linux build step.

Linux packaging must include the compiled extension and validate compatibility with the supported PipeWire runtime.

Native audio acceptance remains necessary because WSL cannot validate actual PipeWire hardware behavior.

The native boundary introduces memory-safety and synchronization responsibilities that do not exist in pure Python. The C API must therefore remain deliberately small, strongly tested, and isolated behind Python abstractions.

## Testing strategy

Most behavior will be tested without hardware by injecting or wrapping the Python-facing native boundary.

Native-shim tests should cover lifecycle, bounded buffering, error propagation, shutdown, overflow behavior and conversion of native records into `AudioFrame` values.

WSL remains authoritative for compilation, Python integration, unit tests, Linux/shared mypy and headless failure behavior.

Native Ubuntu acceptance tests remain authoritative for microphone hardware, Bluetooth behavior, system-output capture, default-device migration and real capture timing.

Hardware acceptance must include at minimum:

```text
default microphone capture
default system-output capture
microphone default-device migration
system-output default-device migration
capture gap preservation
PipeWire unavailable/recovery behavior
start/stop/restart lifecycle
concurrent microphone and system capture
```

## Observability

Linux capture should expose structured events for:

```text
PipeWire connection lifecycle
stream state transitions
negotiated audio format
current/default target observations when available
capture discontinuities
native queue overflow/drop counts
stream errors
recovery attempts and outcomes
device/default transitions
```

Runtime numeric object IDs may be logged for diagnostics but must be clearly treated as transient.

## Reversibility

The decision is isolated behind the existing platform and `AudioCapture` boundaries.

Replacing CFFI with another native binding mechanism later would not require redesigning the shared transcription pipeline.

Replacing PipeWire with another Linux backend would require a new Linux infrastructure implementation but should not require changes to shared application/domain code.

## Follow-up

Production implementation should begin in WSL with the smallest possible native boundary.

The first production milestone should establish the native CFFI module, deterministic lifecycle management, bounded native transport and one microphone `AudioCapture` implementation before adding system-output capture.

Native Ubuntu should then validate the production implementation against the behaviors established by this feasibility spike before Linux packaging work proceeds.
