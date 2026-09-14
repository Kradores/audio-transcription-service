# ADR-050: Interactive Controller and Transcription Runtime Process Boundary

## Status

Accepted

## Date

2026-09-14

## Context

ADR-049 established that the Windows end-user distribution will provide a small interactive controller around the existing transcription application.

The controller must allow a nontechnical user to:

- start the transcription application;
- stop it gracefully;
- understand whether it is running or has failed;
- open logs, configuration, and application data;
- later create a support bundle.

The controller must remain an operational host only. It must not contain transcription, audio capture, VAD, persistence, or other business logic.

The existing application lifecycle is already coordinated through:

```text
run_application()
    ↓
create_application()
    ↓
Application.start()
    ↓
ConversationPipeline.start()
    ↓
runtime processing
    ↓
Application.stop()
    ↓
ConversationPipeline.stop()
```

The current CLI execution model has been extensively validated on Windows with:

- WASAPI loopback capture;
- default microphone capture;
- Windows Core Audio device monitoring;
- Faster-Whisper;
- native audio dependencies;
- SQLite persistence;
- graceful shutdown.

`run_application()` already guarantees that `Application.stop()` executes through a `finally` block when shutdown is requested or when the running application terminates unexpectedly.

The current application components are intentionally designed around one application lifecycle.

Restartability of the same composed `Application`, capture instances, transcription executor, native audio objects, model objects, or SQLite connection has not been established as a supported contract.

The controller therefore needs a lifecycle model that preserves the existing application behavior without forcing these components to become restartable.

### Synchronous startup

Application composition performs significant synchronous work before the application reaches its running state.

This includes construction or initialization of components such as:

- configuration;
- logging;
- SQLite;
- Faster-Whisper runtime;
- Faster-Whisper model;
- audio capture;
- VAD;
- transcription processing.

This work must not execute on the controller UI thread because model and native-runtime initialization may take noticeable time.

### Windows/native execution concerns

The validated transcription application currently executes as the main workload of its process.

Windows Core Audio monitoring and other native dependencies have not been validated with the entire application lifecycle moved onto an arbitrary GUI worker thread.

Moving the transcription application into a background thread inside the controller process would therefore introduce a new threading/native-runtime assumption without providing a current requirement.

### Failure isolation

The first external tester will be nontechnical and the developer will not have direct access to the machine.

If Faster-Whisper, CTranslate2, audio initialization, configuration, or another native dependency fails during startup or runtime, the controller should remain available so that:

- the failure can be shown to the user;
- logs can still be opened;
- a future support bundle can still be created;
- the runtime can be started again after configuration or environment changes.

The controller should therefore not share the same failure domain as the transcription runtime.

---

## Decision

### 1. The controller and transcription runtime will execute in separate processes

The Windows controller will be a long-lived interactive process.

Each transcription session will execute in a separate child runtime process.

The resulting topology is:

```text
┌──────────────────────────────────────┐
│ Windows Controller                   │
│                                      │
│ Status                               │
│ Start / Stop                         │
│ Open Logs                            │
│ Open Configuration                   │
│ Open Data Folder                     │
│ Support Bundle                       │
└──────────────────┬───────────────────┘
                   │
                   │ lifecycle control
                   ▼
┌──────────────────────────────────────┐
│ Transcription Runtime Process        │
│                                      │
│ existing composition                 │
│        ↓                             │
│ existing Application                 │
│        ↓                             │
│ ConversationPipeline                 │
│        ↓                             │
│ audio / VAD / transcription / DB     │
└──────────────────────────────────────┘
```

The controller process does not construct or own transcription-domain components directly.

### 2. Each Start creates a fresh runtime process

A controller Start operation creates a new transcription runtime process.

The runtime process creates a fresh application composition.

Conceptually:

```text
Start
  ↓
new runtime process
  ↓
create_application()
  ↓
Application.start()
```

After that runtime stops, a subsequent Start creates another fresh runtime process and another fresh application composition.

The same `Application` instance is not restarted.

This preserves the existing one-lifecycle semantics of:

- `Application`;
- `ConversationPipeline`;
- audio capture;
- device monitors;
- transcription executor;
- VAD;
- Faster-Whisper;
- SQLite connection.

No component restart API will be introduced solely for the controller.

### 3. The runtime process will reuse the existing application runner

The runtime child will delegate to the existing application composition and lifecycle.

It must not duplicate:

- application construction;
- source startup order;
- source shutdown order;
- executor draining;
- SQLite cleanup;
- audio-device lifecycle;
- transcription lifecycle.

The runtime process will execute the equivalent of:

```text
run_application()
```

using the existing `RuntimePaths`.

The controller is therefore another application host, not another application implementation.

### 4. Normal Stop must use the existing graceful shutdown path

The controller must not normally stop transcription by killing the runtime process.

A Stop operation will signal the runtime process to request application shutdown.

Conceptually:

```text
Controller
    ↓
Stop requested
    ↓
runtime shutdown signal
    ↓
existing run_application()
    ↓
Application.stop()
    ↓
ConversationPipeline.stop()
```

The established shutdown semantics remain responsible for:

```text
stop source production
    ↓
flush pending aggregation
    ↓
stop source pipelines
    ↓
drain accepted executor work
    ↓
stop executor
    ↓
close SQLite
    ↓
exit runtime process
```

Forceful process termination is not part of the normal Stop path.

A future recovery policy for a genuinely unresponsive process may be introduced separately if runtime evidence demonstrates a need.

### 5. Controller lifecycle state will be explicit

The controller will represent runtime lifecycle using the following states:

```text
STOPPED
STARTING
RUNNING
STOPPING
FAILED
```

The expected transitions are:

```text
STOPPED
   │
   │ Start
   ▼
STARTING
   │
   ├── startup succeeds
   │        ↓
   │     RUNNING
   │
   └── startup fails
            ↓
          FAILED
```

and:

```text
RUNNING
   │
   │ Stop
   ▼
STOPPING
   │
   │ graceful runtime exit
   ▼
STOPPED
```

An unexpected runtime exit while starting or running produces:

```text
FAILED
```

The controller will not treat existence of a child process as proof that the application is running.

### 6. RUNNING is reported only after successful application startup

The runtime process must explicitly report successful startup after:

```text
await application.start()
```

has completed.

This distinguishes:

```text
process exists
```

from:

```text
audio sources, executor, and application lifecycle successfully started
```

The controller must therefore not infer readiness from:

- process creation;
- elapsed time;
- log parsing;
- the presence of a PID.

A small readiness notification will be added to the existing application runner where necessary.

### 7. Startup notification must remain generic

The existing application runner may accept a small optional notification callback or equivalent lifecycle notification.

Conceptually:

```python
run_application(
    runtime_paths,
    shutdown_event,
    on_started,
)
```

The notification is emitted only after successful application startup.

The callback must not contain controller-specific behavior.

This keeps `run_application()` reusable by:

- CLI execution;
- controller-hosted execution;
- tests;
- potential future application hosts.

### 8. Controller/runtime communication will remain minimal

The initial implementation will use lightweight local process-control primitives.

Conceptually:

```text
Controller
    │
    ├── shutdown signal ─────────► Runtime
    │
    └── status notifications ◄─── Runtime
```

The required communication is limited to lifecycle information such as:

```text
STARTING
RUNNING
FAILED
STOPPED
```

and a small diagnostic failure summary where appropriate.

No business data will flow through this control channel.

### 9. No network control API will be introduced

The initial controller/runtime boundary will not use:

- HTTP;
- FastAPI;
- WebSockets;
- TCP sockets;
- external message brokers;
- Windows Services;
- distributed IPC infrastructure.

The runtime is local to the same logged-in user and machine.

A lightweight local process-control mechanism is sufficient.

### 10. Runtime failure must not terminate the controller

If application composition or runtime processing fails, the child runtime process may exit.

The controller remains alive.

It transitions to:

```text
FAILED
```

and continues to provide operational functions such as:

- opening logs;
- opening configuration;
- opening the data directory;
- creating a support bundle when implemented;
- starting a fresh runtime process again.

The controller should expose a useful failure summary without attempting to reproduce all diagnostic information that already exists in the application logs.

### 11. Failed startup must leave no reusable partial application state

A failed runtime process is disposable.

A subsequent Start creates a completely new process and application graph.

The controller must not try to repair or reuse:

- partially initialized Whisper models;
- audio capture objects;
- executor instances;
- database connections;
- device monitors;
- application objects.

This favors deterministic fresh composition over complicated lifecycle recovery inside the controller.

### 12. The controller remains operational only

The controller owns:

```text
runtime process lifecycle
controller state
user interaction
opening runtime folders/files
later support-bundle invocation
```

The controller does not own:

```text
audio capture
device selection
normalization
VAD
speech assembly
aggregation
language policy
Whisper
transcription execution
persistence
database schema
```

These remain entirely inside the existing application/runtime process.

### 13. Runtime paths are shared through the existing RuntimePaths boundary

ADR-049 runtime layout and the existing `RuntimePaths` implementation remain authoritative.

The controller and runtime process operate against the same deterministic mutable-data root.

Conceptually:

```text
RuntimePaths
    ├── config
    ├── data
    ├── logs
    ├── diagnostics
    └── support
```

The controller may use these locations to open files and directories.

The transcription runtime receives the same paths through normal dependency injection/composition.

Neither process may discover runtime locations through the current working directory.

### 14. Closing the controller while transcription is running must use graceful stop

Closing the controller window while a runtime is active must behave like an explicit Stop request.

Conceptually:

```text
controller close
    ↓
request graceful runtime shutdown
    ↓
wait for runtime lifecycle completion
    ↓
controller exits
```

The controller must not normally abandon a transcription runtime process when its window closes.

The exact UI interaction during shutdown is an implementation detail.

### 15. Only one runtime process will be active per controller instance

The initial controller will allow at most one active transcription runtime.

While state is:

```text
STARTING
RUNNING
STOPPING
```

another Start operation is invalid.

This prevents multiple runtime instances from competing for:

- the same audio devices;
- the same SQLite database;
- the same log files;
- the same configuration;
- GPU/CPU resources.

Multi-instance operation is not a current requirement.

---

## Rationale

### Preserve the validated runtime execution model

The audio and transcription application already works reliably when executed as the primary workload of its process.

A separate runtime process preserves that model rather than moving native components onto an unvalidated GUI worker thread.

### Keep the UI responsive

Model initialization and native-runtime composition can perform significant synchronous work.

Running them in a separate process prevents that work from freezing the controller UI.

### Strong failure isolation

A native-library, model-loading, or audio-runtime failure can terminate the runtime without also destroying the controller.

This is especially valuable for remote support on a machine the developer cannot access directly.

### Fresh restart semantics

Creating a fresh process per Start naturally creates fresh:

- event loops;
- models;
- native libraries;
- capture objects;
- executor workers;
- SQLite connections.

This avoids adding artificial restartability requirements to components that currently have clean one-lifecycle ownership.

### Minimal coupling

Only lifecycle control crosses the process boundary.

The controller does not need to understand the internal application graph.

### Reuse existing graceful shutdown

Normal Stop remains application-owned rather than process-manager-owned.

The process boundary changes hosting, not application shutdown semantics.

---

## Alternatives Considered

### Run the transcription application directly on the GUI thread

Rejected.

Application composition and ML/native initialization may take significant time and would block the controller UI.

### Run the transcription application on a worker thread inside the controller process

Rejected for the initial implementation.

This would move the complete Windows audio/native runtime into a new threading environment that has not been validated.

It also places controller and transcription failures inside the same process.

### Reuse the same Application instance across Start/Stop cycles

Rejected.

The current architecture establishes one lifecycle for application components and does not promise restartability after shutdown.

Fresh composition is simpler and more reliable.

### Make all application components restartable

Rejected.

This would require lifecycle changes throughout capture, VAD, executors, native models, device monitors, persistence, and orchestration solely to satisfy controller hosting.

There is no current requirement justifying that complexity.

### Stop by terminating the runtime process

Rejected as the normal lifecycle.

The application already owns a coordinated graceful shutdown path that flushes valid work, drains the transcription executor, stops audio sources, and closes SQLite.

Forceful termination would bypass those guarantees.

### Use log messages to infer application readiness

Rejected.

Logs are observability output, not a control contract.

The runtime must provide an explicit lifecycle notification after `Application.start()` succeeds.

### Add a local HTTP/FastAPI control API

Rejected.

The controller and runtime are local processes owned by the same interactive user.

Introducing networking, ports, endpoint lifecycle, authentication considerations, and another failure surface is unnecessary.

### Run the application as a Windows Service

Rejected by ADR-049.

The transcription workload belongs to the logged-in interactive user session and requires interactive audio/device behavior.

### Use external message-broker infrastructure

Rejected.

The lifecycle communication requirement is extremely small and entirely local.

---

## Failure Semantics

### Composition failure

If application composition fails before startup completes:

```text
STARTING
    ↓
FAILED
```

The runtime process exits.

The controller remains running.

### Startup failure

If `Application.start()` fails:

```text
STARTING
    ↓
FAILED
```

Existing application startup rollback remains authoritative.

The controller does not independently clean up application components.

### Unexpected runtime termination

If a source pipeline, executor, or another monitored runtime component terminates unexpectedly:

```text
RUNNING
    ↓
FAILED
```

The existing application runner performs its normal cleanup before runtime exit where possible.

### Requested shutdown

A user Stop produces:

```text
RUNNING
    ↓
STOPPING
    ↓
STOPPED
```

only after the runtime has completed its graceful shutdown path.

---

## Testing Requirements

The process-host implementation must have focused tests covering:

- initial state is `STOPPED`;
- Start creates exactly one runtime;
- state transitions from `STOPPED` → `STARTING`;
- successful readiness transitions to `RUNNING`;
- process existence alone does not produce `RUNNING`;
- normal Stop sends graceful shutdown;
- normal Stop transitions through `STOPPING`;
- graceful runtime exit produces `STOPPED`;
- startup failure produces `FAILED`;
- unexpected runtime exit produces `FAILED`;
- failure information is retained for controller display;
- Start after a failed runtime creates a fresh runtime;
- Start after a normal Stop creates a fresh runtime;
- repeated Start while active is rejected or ignored deterministically;
- repeated Stop is safe;
- controller shutdown requests graceful runtime shutdown;
- no business/transcription logic exists in the controller host;
- child-process cleanup does not leave an orphan runtime;
- runtime paths do not depend on current working directory.

Tests for lifecycle control should use fake runtime targets where possible.

Unit tests must not require:

- audio hardware;
- Faster-Whisper;
- a GPU;
- a real microphone;
- a real WASAPI device.

A real Windows acceptance test must subsequently verify:

```text
controller launches
    ↓
Start
    ↓
runtime reports Running
    ↓
both audio sources operate
    ↓
transcription persists
    ↓
Stop
    ↓
graceful executor drain
    ↓
runtime exits
    ↓
controller reports Stopped
    ↓
Start again
    ↓
fresh runtime operates normally
```

Failure acceptance should also verify that an intentionally invalid runtime configuration produces:

```text
FAILED
```

while the controller remains usable and logs remain accessible.

---

## Observability

Controller/runtime lifecycle events should be observable without duplicating existing application diagnostics.

Useful controller-level events include:

```text
runtime process starting
runtime process started
runtime startup failed
runtime stop requested
runtime process exited
runtime process failed
```

Where useful, include:

```text
runtime process id
exit code
controller state transition
```

The controller must not add transcript content to operational logs.

Detailed audio/transcription diagnostics remain owned by the existing application logging subsystem.

---

## Security and Privacy

Lifecycle IPC is local to the application and must not expose a network service.

Controller status communication must not contain transcript text or captured audio.

Support-bundle privacy remains governed by ADR-049, including explicit handling of transcript database inclusion.

---

## Consequences

### Positive

- The controller remains responsive during slow model/runtime initialization.
- Native audio execution stays close to the already validated process model.
- Runtime crashes are isolated from the controller.
- Start after Stop naturally creates a clean application environment.
- Existing components do not need restart APIs.
- Existing graceful shutdown semantics are preserved.
- Controller code remains independent of transcription internals.
- Remote failure diagnosis becomes easier.
- Future packaging can treat controller and runtime responsibilities explicitly.

### Negative

- A second process introduces lifecycle coordination.
- Controller/runtime status communication must be implemented and tested.
- Packaging must include both controller and runtime entry points.
- Process startup has a small additional overhead.
- Controller shutdown must handle an active child process carefully.
- Installer and PyInstaller configuration must account for the two entry-point roles.
- Runtime state cannot be accessed directly from the controller and must be communicated explicitly when needed.

These costs are acceptable because the boundary improves reliability, lifecycle clarity, UI responsiveness, and remote diagnosability without changing the transcription architecture.

---

## Implementation Sequence

The implementation should proceed incrementally.

### Slice 1 — Runtime process host

Implement the process lifecycle without GUI concerns:

```text
start
stop
status
startup readiness
failure propagation
fresh restart
```

Use fake runtime targets for focused unit tests.

### Slice 2 — Minimal Windows controller

Add:

```text
Status
Start
Stop
```

No additional application functionality.

### Slice 3 — Runtime file access

Add:

```text
Open Logs
Open Configuration
Open Data Folder
```

using `RuntimePaths`.

### Slice 4 — Support bundle

Add support-bundle creation according to ADR-049 and the future support-bundle component design.

### Slice 5 — Packaging

Package the controller/runtime arrangement through the Windows PyInstaller and installer flow established by ADR-049.

---

## Documentation Impact

### `architecture.md`

Document:

```text
Windows Controller
    ↓
runtime process boundary
    ↓
existing Application
```

and clarify that the controller is outside the transcription/audio application core.

### `deployment.md`

Document:

- controller/runtime process topology;
- one active runtime per controller;
- graceful Stop behavior;
- fresh process on each Start;
- runtime failure isolation.

### `development.md`

Document how to run the controller and runtime entry points during development once implemented.

### `testing.md`

Document:

- process-host unit testing;
- lifecycle-state testing;
- controller/runtime Windows acceptance;
- Start → Stop → Start acceptance.

### `observability.md`

Document controller-level lifecycle events and runtime-process failure visibility.

---

## Related Decisions

- ADR-016 — Application Composition Root
- ADR-022 — Shutdown and Lifecycle
- ADR-036 — Decouple Real-Time Audio Processing from Transcription Execution
- ADR-039 — Multi-Source System and Microphone Audio Processing Architecture
- ADR-042 — Concurrent Transcription Execution with Multiple Whisper Workers
- ADR-043 — Coordinate Process-Wide PortAudio Refresh Across Multiple Audio Sources
- ADR-044 — AMD GPU Transcription Runtime and CPU Fallback Strategy
- ADR-049 — Windows End-User Packaging, Runtime Layout and Interactive Control Host