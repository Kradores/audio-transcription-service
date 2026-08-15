# ADR-032: Transcription Result Delivery Contract

## Status

Proposed

## Context

`SpeechPipeline` currently converts completed `SpeechSegment` objects into `TranscriptionResult` objects through the synchronous `Transcriber` contract. The pipeline needs to deliver successful results to downstream application functionality without coupling itself to persistence, APIs, or another concrete consumer.

The project also requires transcription results to remain chronologically ordered and eventually be persisted individually. 

## Decision

`SpeechPipeline` exposes a synchronous `TranscriptionResultHandler` callback accepting a `TranscriptionResult`.

The pipeline invokes the handler after each successful transcription. Transcription remains sequential, preserving result ordering.

The blocking `Transcriber.transcribe()` operation continues to execute through `asyncio.to_thread()`. The result handler executes after the worker operation completes, in the pipeline's asynchronous execution context.

The pipeline does not retain or embed the original `SpeechSegment` audio inside `TranscriptionResult`.

Handler failures propagate to the pipeline and therefore fail the pipeline rather than silently discarding a successfully transcribed result.

Persistence, retry behavior, durability, and database-specific contracts are explicitly outside this decision.

## Consequences

**Positive:**

* Clear boundary between transcription and downstream result handling.
* No coupling between `SpeechPipeline` and SQLite.
* Chronological result delivery is preserved.
* Callback consumers are easy to replace in tests and production.
* Blocking transcription remains isolated from the event loop.
* Future persistence can be introduced without changing the transcription contract.

**Negative:**

* A slow result handler can delay subsequent transcription because delivery remains sequential.
* Handler failure currently terminates the pipeline.
* Durable retry behavior is not provided yet.

## Alternatives considered

1. **Async result callback** — rejected for now because it unnecessarily couples the pipeline to asynchronous consumers.
2. **Event bus/message queue** — rejected as premature; it introduces infrastructure and concurrency semantics that are not currently required.
3. **Direct SQLite persistence inside `SpeechPipeline`** — rejected because it violates dependency separation and makes the pipeline storage-specific.
4. **Return results from `SpeechPipeline` to the caller** — rejected because the pipeline is a long-lived streaming component and results need to be delivered incrementally.

## Follow-up

A later ADR may define the persistence boundary between `TranscriptionResult` and SQLite, including ordering, failure handling, and durability.
