# ADR-034: SQLite Transcript Repository

## Status
**Accepted**

## Context
ADR-033 established `TranscriptRepository` as the persistence abstraction behind `TranscriptRecorder`. We now need the initial concrete persistence implementation using SQLite. The implementation must remain small, testable, dependency-injected, append-only, and independent of application orchestration.

## Decision
Implement `SQLiteTranscriptRepository` using Python's standard-library `sqlite3` module. The repository receives an injected `sqlite3.Connection`, explicitly initializes the `transcripts` schema, and exposes `insert(TranscriptionResult)`. The repository persists `text`, `language`, `confidence`, `start`, `end`, and repository-generated UTC `created_at`; SQLite generates the integer primary key. Inserts are append-only and committed successfully before returning. Repository/database failures propagate unchanged. No query API, migration framework, retry mechanism, transaction abstraction, or persistence DTO is introduced at this stage.

## Consequences

**Positive:**

* Uses SQLite without an additional dependency.
* Real database behavior can be tested with `:memory:`.
* Connection ownership is explicit and dependency-injected.
* Persistence remains replaceable behind `TranscriptRepository`.
* All current `TranscriptionResult` data is preserved.
* Successful `record()` corresponds to committed persistence.

**Negative:**

* Schema evolution is not yet formally managed.
* The repository owns only the initial persistence use case.
* SQLite-specific behavior remains in infrastructure and will need consideration if another database is introduced.

## Alternatives considered

* **Open a new SQLite connection for every insert** — rejected because it introduces unnecessary connection lifecycle overhead and makes resource ownership less explicit.
* **Repository reads database configuration itself** — rejected because configuration belongs to composition.
* **Introduce a database abstraction/ORM** — rejected as unnecessary for the current single-table, append-only workload.
* **Add a migration framework now** — rejected as premature.
* **Persist through a separate persistence DTO** — rejected because ADR-033 explicitly established `TranscriptionResult` as the repository input.
* **Add query/update/delete operations** — rejected because the current requirement is append-only transcript recording.

## Related decisions

* ADR-016 — Application Composition Root
* ADR-033 — Transcription Result Persistence Boundary
