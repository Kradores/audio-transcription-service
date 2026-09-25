# ADR-055: Controller and Runtime Process Logging Ownership

## Status

Accepted

## Context

ADR-017 established the application logging strategy using Python's standard
library logging package and rotating persistent log files.

ADR-050 later introduced a process boundary between:

- the interactive controller process; and
- the transcription runtime child process.

The original logging design predates this process split.

The runtime application currently configures persistent logging when the
runtime child is composed.

The controller process does not independently configure persistent logging.

This means controller-owned operations can occur without being written to the
application log, including:

- Whisper model provisioning;
- controller lifecycle events;
- support-bundle creation;
- runtime-process supervision before the runtime child starts.

This became visible during packaged Whisper model provisioning failure testing:
the controller correctly observed and displayed the provisioning failure, but
the support bundle contained an empty application log.

A naive solution would configure the same RotatingFileHandler path in both
processes.

That is rejected because the controller and runtime would then independently
write to and rotate the same files without application-owned cross-process
coordination.

The project optimizes for explicit ownership and reliability over additional
cleverness.

## Decision

Persistent log-file ownership will follow the process boundary.

The controller process and runtime process will write to separate log files.

### Runtime log

The runtime process keeps ownership of the configured logging file:

```text
logging.file.path
```

For the default Windows configuration this remains conceptually:

```text
logs/audio-transcription-service.log
```

Existing runtime logging behavior therefore remains compatible.

### Controller log

The controller derives a deterministic sibling path from the configured runtime
log path.

For example:

```text
configured runtime log:
logs/audio-transcription-service.log

controller log:
logs/audio-transcription-service.controller.log
```

The controller log uses the same configured:

- log level;
- maximum file size;
- backup count;
- structured log format.

The controller owns this file for the lifetime of the controller process.

The runtime child never writes to it.

### Process ownership invariant

The required invariant is:

```text
controller process
    ↓
audio-transcription-service.controller.log

runtime child process
    ↓
audio-transcription-service.log
```

No persistent rotating log file is owned by more than one process.

### Controller initialization

The controller will load logging configuration and configure its persistent
logging before constructing controller-owned components that can emit useful
events.

This includes, in particular:

- WhisperModelProvisioningHost;
- RuntimeProcessHost;
- support-bundle orchestration.

Model provisioning therefore remains observable even when the transcription
runtime has never started.

### Runtime initialization

The runtime child continues to configure logging through the normal application
composition path.

Each fresh runtime process reloads current configuration and independently
configures its runtime-owned logging file.

### Configuration changes

Controller logging configuration is session-scoped.

Changes to logging configuration made while the controller is already running
do not move or reconfigure the controller's current log file.

A controller restart applies the new controller logging configuration.

Each newly started runtime child continues to read the latest application
configuration.

### Windowed Windows execution

Persistent logging must not depend on the presence of stdout or stderr.

Packaged Windows controller processes may not have console streams.

Console logging is therefore best-effort and must not prevent file logging or
application operation when no console stream exists.

### Log rotation

Controller and runtime logs rotate independently.

For example:

```text
audio-transcription-service.log
audio-transcription-service.log.1
audio-transcription-service.log.2

audio-transcription-service.controller.log
audio-transcription-service.controller.log.1
audio-transcription-service.controller.log.2
```

The same configured rotation limits apply to both process-owned logs.

### Support bundles

Support bundles include both process-owned log families:

```text
runtime log
runtime rotated logs

controller log
controller rotated logs
```

The support-bundle contract must represent multiple application log paths
rather than assuming one persistent log owner.

When configuration cannot be loaded, existing best-effort log discovery under
the runtime logs directory remains available.

### Log correlation

This ADR does not introduce a distributed correlation or session identifier.

Both logs already contain timestamps and logger names.

For the current support requirements, separate timestamped process logs are
sufficient.

Cross-process correlation identifiers may be introduced later if concrete
diagnostic evidence shows they are needed.

## Consequences

### Positive

- Controller failures are persisted even when the runtime never starts.
- Whisper model provisioning becomes diagnosable from support bundles.
- Each rotating file has exactly one process owner.
- Runtime logging behavior remains backward compatible.
- No multiprocessing logging infrastructure is required.
- Controller failures cannot interfere with runtime log rotation.
- Runtime-process restarts do not reconfigure controller logging.
- CPU, NVIDIA, and AMD packaged variants use the same logging ownership model.
- The process boundary remains explicit and observable.

### Negative

- Support bundles contain two log families instead of one.
- Events spanning controller and runtime must be correlated by timestamp.
- Support-bundle path representation becomes slightly more complex.
- Controller logging configuration is fixed for one controller session.
- Total possible retained log storage increases because each process has its
  own rotation set.

These costs are acceptable because they preserve explicit ownership and avoid
cross-process file coordination.

## Alternatives Considered

### Both processes write to the same RotatingFileHandler path

Rejected.

The standard rotating-file configuration is process-local.

Having the controller and runtime independently write and rotate the same files
would create ambiguous file ownership and possible rotation/write races.

### Centralized QueueHandler / QueueListener owned by the controller

Deferred.

A centralized logging queue could provide one ordered persistent log and one
rotation owner.

However, it would require:

- passing logging queues across the process boundary;
- listener lifecycle management;
- shutdown coordination;
- behavior for runtime failure or controller failure;
- additional multiprocessing-specific logging configuration.

The current requirement does not justify that complexity.

It can be reconsidered if unified cross-process ordering becomes necessary.

### Runtime sends log events through the existing runtime status channel

Rejected.

Runtime status events are a bounded typed control/diagnostic contract.

General application logs have different volume, retention, and failure
semantics and should not overload that channel.

### Persist only controller logs

Rejected.

The runtime contains most capture, inference, recovery, and transcription
observability and must retain persistent logs.

### Leave controller logging console-only

Rejected.

Packaged Windows execution may not have a usable console, and controller
failures may occur before the runtime child exists.

The observed Whisper provisioning failure demonstrated that this loses
important support evidence.

## Testing Requirements

Automated tests must cover:

- deterministic derivation of the controller log path;
- the controller and runtime log paths are distinct;
- existing runtime logging continues to use the configured path;
- controller logging writes to the controller-owned path;
- configured level and rotation settings are preserved;
- logging does not fail when no console stream is available;
- repeated controller logging configuration does not duplicate handlers;
- support bundles include the runtime log;
- support bundles include runtime rotations;
- support bundles include the controller log;
- support bundles include controller rotations;
- duplicate log paths are not archived twice;
- configuration-load failure retains best-effort log discovery behavior.

Packaged Windows acceptance must verify:

```text
start controller
    ↓
perform model provisioning without starting runtime
    ↓
controller log contains provisioning lifecycle events
    ↓
create support bundle
    ↓
controller log is included
```

A second acceptance verifies:

```text
start runtime
    ↓
produce normal runtime events
    ↓
stop runtime
    ↓
create support bundle
    ↓
both controller and runtime logs are included
```

## Implementation Validation

ADR-055 has been implemented and validated through automated tests and a
packaged Windows AMD installation.

Automated validation covers:

- deterministic controller-log path derivation;
- explicit persistent-path override without changing other logging settings;
- safe logging when stderr is unavailable;
- controller logging configuration before controller-owned components;
- separate runtime and controller log paths;
- independent rotation-family collection;
- duplicate log-path suppression;
- support-bundle fallback when configuration cannot be loaded.

Packaged acceptance used the production windowed AMD controller.

Before the transcription runtime was started, provisioning the `tiny` model
produced:

```text
audio-transcription-service.controller.log
```

containing controller startup and model-provisioning lifecycle events.

At that point:

```text
audio-transcription-service.log
```

did not exist.

A support bundle created in this controller-only state contained the controller
log and no runtime log.

The runtime was then started and stopped normally.

After runtime execution both process-owned logs existed:

```text
audio-transcription-service.controller.log
audio-transcription-service.log
```

A second support bundle contained both logs.

The final repository quality gate completed with:

```text
ruff format: clean
ruff check: clean
mypy: clean across 178 source files
pytest: 686 passed
```

The two existing Python 3.14 `torch.jit.load` deprecation warnings remain known
and unrelated.

This validation also closes the provisioning-observability gap discovered
during ADR-054 packaged acceptance: controller-owned model provisioning is now
persistently diagnosable without requiring the transcription runtime to start.

## Implementation Validation

ADR-055 has been implemented and validated through automated tests and a
packaged Windows AMD installation.

Automated validation covers:

- deterministic controller-log path derivation;
- distinct controller and runtime log ownership;
- preservation of configured logging level and rotation settings;
- safe persistent logging when stderr is unavailable;
- controller logging configuration before controller-owned components;
- collection of controller and runtime log families and their rotations;
- duplicate log-path suppression;
- best-effort log discovery when configuration cannot be loaded.

Packaged acceptance used the production windowed AMD controller.

Before the transcription runtime was started, provisioning the `tiny` Whisper
model created:

```text
audio-transcription-service.controller.log

## Related Decisions

- ADR-014 — Package Dependency Direction
- ADR-016 — Application Composition Root
- ADR-017 — Logging Strategy
- ADR-049 — Windows End-User Packaging, Runtime Layout and Interactive Control Host
- ADR-050 — Interactive Controller and Transcription Runtime Process Boundary
- ADR-052 — Deterministic Distribution Metadata for Support Diagnostics
- ADR-053 — Runtime-Observed Hardware and Transcription Diagnostics Across the Controller Process Boundary
- ADR-054 — Local Whisper Model Provisioning and Offline Runtime Startup