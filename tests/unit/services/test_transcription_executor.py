from __future__ import annotations

import asyncio
import logging
import threading

import pytest

from app.audio.contracts import SpeechSegment
from app.services.transcription_executor import TranscriptionExecutorImpl
from app.transcription.contracts import (
    AudioSource,
    SourcedTranscriptionResult,
    TranscriptionResult,
    TranscriptionWorkItem,
)


def create_segment(timestamp: float = 0.0) -> SpeechSegment:
    import numpy as np

    from app.audio.contracts import AudioFormat

    return SpeechSegment(
        audio=np.zeros((16_000, 1), dtype=np.float32),
        timestamp=timestamp,
        duration=1.0,
        format=AudioFormat(
            sample_rate=16_000,
            channels=1,
            sample_type="float32",
        ),
    )


def create_transcription_work_item(
    source: AudioSource = AudioSource.SYSTEM_AUDIO, timestamp: float = 0.0
) -> TranscriptionWorkItem:
    return TranscriptionWorkItem(source=source, segment=create_segment(timestamp=timestamp))


def create_sourced_result(
    item: TranscriptionWorkItem,
) -> SourcedTranscriptionResult:
    segment = item.segment

    return SourcedTranscriptionResult(
        source=item.source,
        result=TranscriptionResult(
            text="text",
            language="en",
            confidence=None,
            start=segment.timestamp,
            end=segment.timestamp + segment.duration,
        ),
    )


class FakeProcessor:
    def __init__(self) -> None:
        self.processed: list[TranscriptionWorkItem] = []

    def process(
        self,
        item: TranscriptionWorkItem,
    ) -> SourcedTranscriptionResult:
        self.processed.append(item)

        return create_sourced_result(item)


@pytest.mark.anyio
async def test_executor_processes_submitted_segment() -> None:
    processor = FakeProcessor()
    results: list[SourcedTranscriptionResult] = []

    executor = TranscriptionExecutorImpl(
        processors=(processor,),
        on_result=results.append,
        queue_capacity=10,
    )

    await executor.start()

    item = create_transcription_work_item()

    assert executor.submit(item) is True

    await executor.stop()

    assert processor.processed == [item]
    assert len(results) == 1
    assert results[0].result.start == item.segment.timestamp
    assert results[0].source is item.source


@pytest.mark.anyio
async def test_executor_preserves_submission_order() -> None:
    processor = FakeProcessor()
    results: list[SourcedTranscriptionResult] = []

    executor = TranscriptionExecutorImpl(
        processors=(processor,),
        on_result=results.append,
        queue_capacity=10,
    )

    await executor.start()

    items = [
        create_transcription_work_item(timestamp=0.0),
        create_transcription_work_item(timestamp=1.0),
        create_transcription_work_item(timestamp=2.0),
    ]

    for item in items:
        assert executor.submit(item) is True

    await executor.stop()

    assert processor.processed == items
    assert [result.result.start for result in results] == [0.0, 1.0, 2.0]


@pytest.mark.anyio
async def test_executor_submit_does_not_block_while_transcription_is_running() -> None:
    started = threading.Event()
    release = threading.Event()

    class BlockingProcessor:
        def process(
            self,
            item: TranscriptionWorkItem,
        ) -> SourcedTranscriptionResult:
            started.set()
            release.wait()

            return create_sourced_result(item)

    executor = TranscriptionExecutorImpl(
        processors=(BlockingProcessor(),),
        on_result=lambda _: None,
        queue_capacity=10,
    )

    await executor.start()

    first = create_transcription_work_item(timestamp=0.0)
    second = create_transcription_work_item(timestamp=1.0)

    assert executor.submit(first) is True

    await asyncio.to_thread(started.wait)

    # The worker is blocked in transcription, but submit() must remain immediate.
    assert executor.submit(second) is True

    release.set()

    await executor.stop()


@pytest.mark.anyio
async def test_executor_rejects_segment_when_queue_is_full() -> None:
    started = threading.Event()
    release = threading.Event()

    class BlockingProcessor:
        def process(
            self,
            item: TranscriptionWorkItem,
        ) -> SourcedTranscriptionResult:
            started.set()
            release.wait()

            return create_sourced_result(item)

    executor = TranscriptionExecutorImpl(
        processors=(BlockingProcessor(),),
        on_result=lambda _: None,
        queue_capacity=1,
    )

    await executor.start()

    first = create_transcription_work_item(timestamp=0.0)
    second = create_transcription_work_item(timestamp=1.0)
    third = create_transcription_work_item(timestamp=2.0)

    assert executor.submit(first) is True

    await asyncio.to_thread(started.wait)

    assert executor.submit(second) is True
    assert executor.submit(third) is False

    release.set()

    await executor.stop()


@pytest.mark.anyio
async def test_executor_recovers_after_queue_overflow() -> None:
    block_processor = threading.Event()
    result_received = threading.Event()

    class BlockingProcessor:
        def process(
            self,
            item: TranscriptionWorkItem,
        ) -> SourcedTranscriptionResult:
            block_processor.wait()

            return create_sourced_result(item)

    executor = TranscriptionExecutorImpl(
        processors=(BlockingProcessor(),),
        on_result=lambda _: result_received.set(),  # Signal when an item finishes
        queue_capacity=1,
    )

    await executor.start()

    # 1. Fill the executor to its absolute limit
    assert executor.submit(create_transcription_work_item(timestamp=0.0)) is True
    assert executor.submit(create_transcription_work_item(timestamp=1.0)) is False

    # 2. Unblock the worker thread to let it finish the first segment
    block_processor.set()

    # 3. Wait safely until the first segment finishes processing
    await asyncio.to_thread(result_received.wait)

    # 4. Prove the executor recovered: a new segment is now successfully submitted
    assert executor.submit(create_transcription_work_item(timestamp=3.0)) is True

    await executor.stop()


@pytest.mark.anyio
async def test_executor_continues_after_transcription_failure() -> None:
    class FailingProcessor:
        def __init__(self) -> None:
            self.calls = 0

        def process(
            self,
            item: TranscriptionWorkItem,
        ) -> SourcedTranscriptionResult:
            self.calls += 1

            if self.calls == 1:
                raise RuntimeError("transcription failed")

            return create_sourced_result(item)

    processor = FailingProcessor()
    results: list[SourcedTranscriptionResult] = []

    executor = TranscriptionExecutorImpl(
        processors=(processor,),
        on_result=results.append,
        queue_capacity=10,
    )

    await executor.start()

    assert executor.submit(create_transcription_work_item(timestamp=0.0)) is True
    assert executor.submit(create_transcription_work_item(timestamp=1.0)) is True

    await executor.stop()

    assert processor.calls == 2
    assert len(results) == 1


@pytest.mark.anyio
async def test_executor_stop_drains_accepted_segments() -> None:
    processor = FakeProcessor()
    results: list[SourcedTranscriptionResult] = []

    executor = TranscriptionExecutorImpl(
        processors=(processor,),
        on_result=results.append,
        queue_capacity=10,
    )

    await executor.start()

    items = [
        create_transcription_work_item(timestamp=0.0),
        create_transcription_work_item(timestamp=1.0),
        create_transcription_work_item(timestamp=2.0),
    ]

    for item in items:
        assert executor.submit(item) is True

    await executor.stop()

    assert processor.processed == items
    assert len(results) == 3


@pytest.mark.anyio
async def test_executor_stats_track_accepted_submissions() -> None:
    executor = TranscriptionExecutorImpl(
        processors=(FakeProcessor(),),
        on_result=lambda _: None,
        queue_capacity=10,
    )

    await executor.start()

    assert executor.submit(create_transcription_work_item(timestamp=0.0)) is True
    assert executor.submit(create_transcription_work_item(timestamp=1.0)) is True

    await executor.stop()

    stats = executor.stats

    assert stats.submitted == 2


@pytest.mark.anyio
async def test_executor_stats_track_rejected_submissions() -> None:
    started = threading.Event()
    release = threading.Event()

    class BlockingProcessor:
        def process(
            self,
            item: TranscriptionWorkItem,
        ) -> SourcedTranscriptionResult:
            started.set()
            release.wait()

            return create_sourced_result(item)

    executor = TranscriptionExecutorImpl(
        processors=(BlockingProcessor(),),
        on_result=lambda _: None,
        queue_capacity=1,
    )

    await executor.start()

    assert executor.submit(create_transcription_work_item(timestamp=0.0)) is True

    await asyncio.to_thread(started.wait)

    assert executor.submit(create_transcription_work_item(timestamp=1.0)) is True
    assert executor.submit(create_transcription_work_item(timestamp=2.0)) is False
    assert executor.submit(create_transcription_work_item(timestamp=3.0)) is False

    release.set()

    await executor.stop()

    stats = executor.stats

    assert stats.rejected == 2


@pytest.mark.anyio
async def test_executor_stats_track_completed_transcriptions() -> None:
    processor = FakeProcessor()

    executor = TranscriptionExecutorImpl(
        processors=(processor,),
        on_result=lambda _: None,
        queue_capacity=10,
    )

    await executor.start()

    assert executor.submit(create_transcription_work_item(timestamp=0.0)) is True
    assert executor.submit(create_transcription_work_item(timestamp=1.0)) is True
    assert executor.submit(create_transcription_work_item(timestamp=2.0)) is True

    await executor.stop()

    stats = executor.stats

    assert stats.submitted == 3
    assert stats.completed == 3
    assert stats.failed == 0


@pytest.mark.anyio
async def test_executor_stats_track_transcription_failures() -> None:
    class FailingProcessor:
        def __init__(self) -> None:
            self.calls = 0

        def process(
            self,
            item: TranscriptionWorkItem,
        ) -> SourcedTranscriptionResult:
            self.calls += 1

            if self.calls <= 2:
                raise RuntimeError("transcription failed")

            return create_sourced_result(item)

    executor = TranscriptionExecutorImpl(
        processors=(FailingProcessor(),),
        on_result=lambda _: None,
        queue_capacity=10,
    )

    await executor.start()

    assert executor.submit(create_transcription_work_item(timestamp=0.0)) is True
    assert executor.submit(create_transcription_work_item(timestamp=1.0)) is True
    assert executor.submit(create_transcription_work_item(timestamp=2.0)) is True

    await executor.stop()

    stats = executor.stats

    assert stats.submitted == 3
    assert stats.completed == 1
    assert stats.failed == 2


@pytest.mark.anyio
async def test_executor_stats_track_max_queue_depth() -> None:
    started = threading.Event()
    release = threading.Event()

    class BlockingProcessor:
        def process(
            self,
            item: TranscriptionWorkItem,
        ) -> SourcedTranscriptionResult:
            started.set()
            release.wait()

            return create_sourced_result(item)

    executor = TranscriptionExecutorImpl(
        processors=(BlockingProcessor(),),
        on_result=lambda _: None,
        queue_capacity=3,
    )

    await executor.start()

    assert executor.submit(create_transcription_work_item(timestamp=0.0)) is True

    await asyncio.to_thread(started.wait)

    assert executor.submit(create_transcription_work_item(timestamp=1.0)) is True
    assert executor.submit(create_transcription_work_item(timestamp=2.0)) is True
    assert executor.submit(create_transcription_work_item(timestamp=3.0)) is True

    stats = executor.stats

    assert stats.queue_high_water_mark == 3

    release.set()

    await executor.stop()


@pytest.mark.anyio
async def test_executor_stats_are_snapshot() -> None:
    executor = TranscriptionExecutorImpl(
        processors=(FakeProcessor(),),
        on_result=lambda _: None,
        queue_capacity=10,
    )

    await executor.start()

    assert executor.submit(create_transcription_work_item()) is True

    stats_before = executor.stats

    assert stats_before.submitted == 1

    assert executor.submit(create_transcription_work_item(timestamp=1.0)) is True

    stats_after = executor.stats

    assert stats_before.submitted == 1
    assert stats_after.submitted == 2

    await executor.stop()


@pytest.mark.anyio
async def test_executor_preserves_source_on_results() -> None:
    processor = FakeProcessor()
    results: list[SourcedTranscriptionResult] = []

    executor = TranscriptionExecutorImpl(
        processors=(processor,),
        on_result=results.append,
        queue_capacity=10,
    )

    await executor.start()

    assert executor.submit(
        create_transcription_work_item(
            source=AudioSource.SYSTEM_AUDIO,
            timestamp=1.0,
        )
    )
    assert executor.submit(
        create_transcription_work_item(
            source=AudioSource.MICROPHONE,
            timestamp=2.0,
        )
    )

    await executor.stop()

    assert [result.source for result in results] == [
        AudioSource.SYSTEM_AUDIO,
        AudioSource.MICROPHONE,
    ]


@pytest.mark.anyio
async def test_executor_preserves_source_on_transcription_result() -> None:
    # Arrange
    processor = FakeProcessor()
    results: list[SourcedTranscriptionResult] = []

    executor = TranscriptionExecutorImpl(
        processors=(processor,),
        on_result=results.append,
        queue_capacity=10,
    )

    item = create_transcription_work_item(
        source=AudioSource.MICROPHONE,
    )

    await executor.start()

    # Act
    assert executor.submit(item) is True
    await executor.stop()

    # Assert
    assert len(results) == 1
    assert results[0].source is item.source


def test_executor_requires_at_least_one_transcription_processor() -> None:
    with pytest.raises(
        ValueError,
        match="at least one transcription processor is required",
    ):
        TranscriptionExecutorImpl(
            processors=(),
            on_result=lambda _: None,
            queue_capacity=10,
        )


def test_executor_initial_concurrency_stats() -> None:
    # Arrange
    executor = TranscriptionExecutorImpl(
        processors=(FakeProcessor(),),
        on_result=lambda _: None,
        queue_capacity=10,
    )

    stats = executor.stats

    # Assert
    assert stats.worker_count == 1
    assert stats.active_workers == 0
    assert stats.active_workers_high_water_mark == 0


@pytest.mark.anyio
async def test_executor_processes_different_sources_concurrently() -> None:
    first_started = threading.Event()
    second_started = threading.Event()
    release = threading.Event()

    class BlockingProcessor:
        def __init__(self, started: threading.Event) -> None:
            self._started = started
            self.calls = 0

        def process(
            self,
            item: TranscriptionWorkItem,
        ) -> SourcedTranscriptionResult:
            self.calls += 1
            self._started.set()
            release.wait()

            return create_sourced_result(item)

    first = BlockingProcessor(first_started)
    second = BlockingProcessor(second_started)

    executor = TranscriptionExecutorImpl(
        processors=(first, second),
        on_result=lambda _: None,
        queue_capacity=10,
    )

    await executor.start()

    assert executor.submit(
        create_transcription_work_item(
            source=AudioSource.MICROPHONE,
            timestamp=0.0,
        )
    )

    assert executor.submit(
        create_transcription_work_item(
            source=AudioSource.SYSTEM_AUDIO,
            timestamp=1.0,
        )
    )

    await asyncio.to_thread(first_started.wait)
    await asyncio.to_thread(second_started.wait)

    stats_while_running = executor.stats

    assert stats_while_running.worker_count == 2
    assert stats_while_running.active_workers == 2
    assert stats_while_running.active_workers_high_water_mark == 2

    release.set()

    await executor.stop()

    stats_after_stop = executor.stats

    assert first.calls == 1
    assert second.calls == 1
    assert stats_after_stop.active_workers == 0
    assert stats_after_stop.active_workers_high_water_mark == 2


@pytest.mark.anyio
async def test_executor_accounts_for_all_accepted_work_after_shutdown() -> None:
    class SelectiveProcessor:
        def process(
            self,
            item: TranscriptionWorkItem,
        ) -> SourcedTranscriptionResult:
            if int(item.segment.timestamp) % 2 == 0:
                raise RuntimeError("transcription failed")

            return create_sourced_result(item)

    executor = TranscriptionExecutorImpl(
        processors=(
            SelectiveProcessor(),
            SelectiveProcessor(),
        ),
        on_result=lambda _: None,
        queue_capacity=10,
    )

    await executor.start()

    for timestamp in range(6):
        assert executor.submit(
            create_transcription_work_item(
                timestamp=float(timestamp),
            )
        )

    await executor.stop()

    stats = executor.stats

    assert stats.submitted == 6
    assert stats.completed == 3
    assert stats.failed == 3
    assert stats.submitted == stats.completed + stats.failed


@pytest.mark.anyio
async def test_executor_stop_is_safe_when_called_multiple_times() -> None:
    executor = TranscriptionExecutorImpl(
        processors=(
            FakeProcessor(),
            FakeProcessor(),
        ),
        on_result=lambda _: None,
        queue_capacity=1,
    )

    await executor.stop()

    await executor.start()
    await executor.stop()
    await executor.stop()


@pytest.mark.anyio
async def test_executor_wait_reports_unexpected_worker_termination() -> None:
    class WorkerFatalError(BaseException):
        pass

    def fail_result_handler(
        _: SourcedTranscriptionResult,
    ) -> None:
        raise WorkerFatalError("worker lifecycle failure")

    executor = TranscriptionExecutorImpl(
        processors=(
            FakeProcessor(),
            FakeProcessor(),
        ),
        on_result=fail_result_handler,
        queue_capacity=10,
    )

    await executor.start()

    assert executor.submit(
        create_transcription_work_item(),
    )

    with pytest.raises(
        RuntimeError,
        match="worker terminated unexpectedly",
    ):
        await executor.wait()

    with pytest.raises(
        RuntimeError,
        match="worker terminated unexpectedly",
    ):
        await executor.stop()


@pytest.mark.anyio
async def test_executor_allows_different_sources_to_complete_out_of_submission_order() -> None:
    first_started = threading.Event()
    second_started = threading.Event()

    release_first = threading.Event()
    release_second = threading.Event()

    results: list[SourcedTranscriptionResult] = []
    second_completed = asyncio.Event()

    class ControlledProcessor:
        def process(
            self,
            item: TranscriptionWorkItem,
        ) -> SourcedTranscriptionResult:
            if item.segment.timestamp == 0.0:
                first_started.set()
                release_first.wait()
            else:
                second_started.set()
                release_second.wait()

            return create_sourced_result(item)

    def handle_result(
        result: SourcedTranscriptionResult,
    ) -> None:
        results.append(result)

        if result.result.start == 1.0:
            second_completed.set()

    executor = TranscriptionExecutorImpl(
        processors=(
            ControlledProcessor(),
            ControlledProcessor(),
        ),
        on_result=handle_result,
        queue_capacity=10,
    )

    await executor.start()

    assert executor.submit(
        create_transcription_work_item(
            source=AudioSource.MICROPHONE,
            timestamp=0.0,
        )
    )

    assert executor.submit(
        create_transcription_work_item(
            source=AudioSource.SYSTEM_AUDIO,
            timestamp=1.0,
        )
    )

    await asyncio.to_thread(first_started.wait)
    await asyncio.to_thread(second_started.wait)

    release_second.set()
    await second_completed.wait()

    assert [result.result.start for result in results] == [1.0]

    release_first.set()
    await executor.stop()

    assert [result.result.start for result in results] == [
        1.0,
        0.0,
    ]


@pytest.mark.anyio
async def test_executor_logs_worker_count_and_worker_lifecycle(
    caplog: pytest.LogCaptureFixture,
) -> None:
    executor = TranscriptionExecutorImpl(
        processors=(
            FakeProcessor(),
            FakeProcessor(),
        ),
        on_result=lambda _: None,
        queue_capacity=10,
    )

    with caplog.at_level(
        logging.INFO,
        logger="app.services.transcription_executor",
    ):
        await executor.start()
        await executor.stop()

    messages = [record.getMessage() for record in caplog.records]

    assert ("transcription executor started queue_capacity=10 worker_count=2") in messages

    assert "transcription worker started worker_id=1" in messages
    assert "transcription worker started worker_id=2" in messages

    assert "transcription worker stopped worker_id=1" in messages
    assert "transcription worker stopped worker_id=2" in messages


@pytest.mark.anyio
async def test_executor_completion_log_includes_worker_identity(
    caplog: pytest.LogCaptureFixture,
) -> None:
    executor = TranscriptionExecutorImpl(
        processors=(
            FakeProcessor(),
            FakeProcessor(),
        ),
        on_result=lambda _: None,
        queue_capacity=10,
    )

    with caplog.at_level(
        logging.INFO,
        logger="app.services.transcription_executor",
    ):
        await executor.start()

        assert executor.submit(
            create_transcription_work_item(
                source=AudioSource.MICROPHONE,
                timestamp=3.0,
            )
        )

        assert executor.submit(
            create_transcription_work_item(
                source=AudioSource.MICROPHONE,
                timestamp=3.0,
            )
        )

        assert executor.submit(
            create_transcription_work_item(
                source=AudioSource.MICROPHONE,
                timestamp=4.0,
            )
        )

        await executor.stop()

    assert any(
        "transcription completed "
        "worker_id=1 source=microphone start=3.000 end=4.000 "
        "duration=1.000 language=en confidence=none" in record.getMessage()
        for record in caplog.records
    )

    assert any(
        "worker_count=2 max_active_workers=1" in record.getMessage() for record in caplog.records
    )


@pytest.mark.anyio
async def test_cancelling_wait_does_not_cancel_executor_lifecycle() -> None:
    processor_started = threading.Event()
    release_processor = threading.Event()

    class BlockingProcessor:
        def process(
            self,
            item: TranscriptionWorkItem,
        ) -> SourcedTranscriptionResult:
            processor_started.set()
            release_processor.wait()

            return create_sourced_result(item)

    results: list[SourcedTranscriptionResult] = []

    executor = TranscriptionExecutorImpl(
        processors=(BlockingProcessor(),),
        on_result=results.append,
        queue_capacity=10,
    )

    await executor.start()

    assert executor.submit(
        create_transcription_work_item(timestamp=1.0),
    )

    await asyncio.to_thread(processor_started.wait)

    wait_task = asyncio.create_task(executor.wait())

    await asyncio.sleep(0)

    wait_task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await wait_task

    stop_task = asyncio.create_task(executor.stop())

    await asyncio.sleep(0)

    assert not stop_task.done()

    release_processor.set()

    await stop_task

    assert len(results) == 1
    assert executor.stats.submitted == 1
    assert executor.stats.completed == 1
    assert executor.stats.failed == 0


@pytest.mark.anyio
async def test_executor_serializes_work_from_same_source() -> None:
    first_started = threading.Event()
    second_started = threading.Event()
    release_first = threading.Event()

    processed_timestamps: list[float] = []

    class FirstProcessor:
        def process(
            self,
            item: TranscriptionWorkItem,
        ) -> SourcedTranscriptionResult:
            processed_timestamps.append(item.segment.timestamp)
            first_started.set()
            release_first.wait()

            return create_sourced_result(item)

    class SecondProcessor:
        def process(
            self,
            item: TranscriptionWorkItem,
        ) -> SourcedTranscriptionResult:
            processed_timestamps.append(item.segment.timestamp)
            second_started.set()

            return create_sourced_result(item)

    executor = TranscriptionExecutorImpl(
        processors=(
            FirstProcessor(),
            SecondProcessor(),
        ),
        on_result=lambda _: None,
        queue_capacity=10,
    )

    await executor.start()

    assert executor.submit(
        create_transcription_work_item(
            source=AudioSource.MICROPHONE,
            timestamp=0.0,
        )
    )

    assert executor.submit(
        create_transcription_work_item(
            source=AudioSource.MICROPHONE,
            timestamp=1.0,
        )
    )

    await asyncio.to_thread(first_started.wait)

    # Give the second executor worker a chance to dequeue the second item.
    await asyncio.sleep(0.05)

    assert not second_started.is_set()

    release_first.set()

    await asyncio.to_thread(second_started.wait)

    await executor.stop()

    assert processed_timestamps == [
        0.0,
        1.0,
    ]
