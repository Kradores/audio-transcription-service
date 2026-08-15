# ADR-033: Transcription Result Persistence Boundary

## Status

**Accepted**

## Context

`SpeechPipeline` produces `TranscriptionResult` objects and delivers them through `TranscriptionResultHandler`. The application must persist completed transcription results in SQLite, but the speech-processing pipeline should remain independent of the persistence technology.

Directly coupling `SpeechPipeline` to SQLite or a persistence repository would mix audio/transcription orchestration with storage concerns.

## Decision

Introduce an application-level `TranscriptRecorder` abstraction responsible for transitioning a completed `TranscriptionResult` into persistent storage.

`SpeechPipeline` continues to depend only on `TranscriptionResultHandler`.

The `TranscriptRecorder` delegates persistence to a `TranscriptRepository` abstraction.

The initial contracts are synchronous:

```text
TranscriptRecorder.record(result)
        ↓
TranscriptRepository.insert(result)
```

`TranscriptionResult` is used directly as the input to persistence; no additional persistence DTO is introduced at this stage.

Persistence is append-only. Existing transcript records are not updated or overwritten.

Persistence failures propagate through the recorder and result handler to the pipeline. Failures are not silently swallowed.

Retry, durability/recovery, transaction strategy, and SQLite-specific implementation details are outside this decision.

## Consequences

**Positive**

* `SpeechPipeline` remains completely storage-agnostic.
* SQLite can be replaced without changing the pipeline.
* Persistence behavior has a dedicated application boundary.
* Repository implementations remain small and focused.
* Tests can use an in-memory/fake repository.
* Future logging, metrics, validation, or retry policy can be added to `TranscriptRecorder` without changing the pipeline.

**Negative**

* Introduces an additional abstraction even though the initial recorder may simply delegate to the repository.
* Persistence failures currently terminate the pipeline.
* No retry/recovery mechanism exists yet.

## Alternatives considered

**1. Pipeline directly writes to SQLite**

Rejected because it couples audio/transcription orchestration to persistence technology.

**2. Pipeline directly depends on `TranscriptRepository`**

Rejected because it still couples the pipeline to a persistence-oriented abstraction and gives the pipeline responsibility for the application persistence workflow.

**3. Use `TranscriptStore` as the application abstraction**

Rejected in favor of `TranscriptRecorder` because the immediate use case is append-only recording of completed transcriptions, while "store" implies broader CRUD/query responsibilities.

**4. Event bus/message queue**

Rejected as premature. It introduces concurrency, delivery, durability, and lifecycle semantics that are not currently required.

**5. Async recorder/repository contracts**

Rejected for now. The persistence implementation can be executed appropriately at the infrastructure/execution boundary without forcing asynchronous semantics into the application contracts.
