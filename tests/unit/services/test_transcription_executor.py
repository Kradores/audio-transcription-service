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


class FakeTranscriber:
    def __init__(self) -> None:
        self.transcribed: list[SpeechSegment] = []

    def transcribe(self, segment: SpeechSegment) -> TranscriptionResult:
        self.transcribed.append(segment)

        return TranscriptionResult(
            text="text",
            language="en",
            confidence=None,
            start=segment.timestamp,
            end=segment.timestamp + segment.duration,
        )


@pytest.mark.anyio
async def test_executor_processes_submitted_segment() -> None:
    transcriber = FakeTranscriber()
    results: list[SourcedTranscriptionResult] = []

    executor = TranscriptionExecutorImpl(
        transcribers=(transcriber,),
        on_result=results.append,
        queue_capacity=10,
    )

    await executor.start()

    item = create_transcription_work_item()

    assert executor.submit(item) is True

    await executor.stop()

    assert transcriber.transcribed == [item.segment]
    assert len(results) == 1
    assert results[0].result.start == item.segment.timestamp
    assert results[0].source is item.source


@pytest.mark.anyio
async def test_executor_preserves_submission_order() -> None:
    transcriber = FakeTranscriber()
    results: list[SourcedTranscriptionResult] = []

    executor = TranscriptionExecutorImpl(
        transcribers=(transcriber,),
        on_result=results.append,
        queue_capacity=10,
    )

    await executor.start()

    items = [
        create_transcription_work_item(timestamp=0.0),
        create_transcription_work_item(timestamp=1.0),
        create_transcription_work_item(timestamp=2.0),
    ]

    segments = [item.segment for item in items]

    for item in items:
        assert executor.submit(item) is True

    await executor.stop()

    assert transcriber.transcribed == segments
    assert [result.result.start for result in results] == [0.0, 1.0, 2.0]


@pytest.mark.anyio
async def test_executor_submit_does_not_block_while_transcription_is_running() -> None:
    started = threading.Event()
    release = threading.Event()

    class BlockingTranscriber:
        def transcribe(self, segment: SpeechSegment) -> TranscriptionResult:
            started.set()
            release.wait()

            return TranscriptionResult(
                text="text",
                language="en",
                confidence=None,
                start=segment.timestamp,
                end=segment.timestamp + segment.duration,
            )

    executor = TranscriptionExecutorImpl(
        transcribers=(BlockingTranscriber(),),
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

    class BlockingTranscriber:
        def transcribe(self, segment: SpeechSegment) -> TranscriptionResult:
            started.set()
            release.wait()

            return TranscriptionResult(
                text="text",
                language="en",
                confidence=None,
                start=segment.timestamp,
                end=segment.timestamp + segment.duration,
            )

    executor = TranscriptionExecutorImpl(
        transcribers=(BlockingTranscriber(),),
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
    block_transcriber = threading.Event()
    result_received = threading.Event()

    class BlockingTranscriber:
        def transcribe(self, segment: SpeechSegment) -> TranscriptionResult:
            block_transcriber.wait()  # Pause the worker thread here
            return TranscriptionResult(
                text="text",
                language="en",
                confidence=None,
                start=segment.timestamp,
                end=segment.timestamp + segment.duration,
            )

    executor = TranscriptionExecutorImpl(
        transcribers=(BlockingTranscriber(),),
        on_result=lambda _: result_received.set(),  # Signal when an item finishes
        queue_capacity=1,
    )

    await executor.start()

    # 1. Fill the executor to its absolute limit
    assert executor.submit(create_transcription_work_item(timestamp=0.0)) is True
    assert executor.submit(create_transcription_work_item(timestamp=1.0)) is False

    # 2. Unblock the worker thread to let it finish the first segment
    block_transcriber.set()

    # 3. Wait safely until the first segment finishes processing
    await asyncio.to_thread(result_received.wait)

    # 4. Prove the executor recovered: a new segment is now successfully submitted
    assert executor.submit(create_transcription_work_item(timestamp=3.0)) is True

    await executor.stop()


@pytest.mark.anyio
async def test_executor_continues_after_transcription_failure() -> None:
    class FailingTranscriber:
        def __init__(self) -> None:
            self.calls = 0

        def transcribe(self, segment: SpeechSegment) -> TranscriptionResult:
            self.calls += 1

            if self.calls == 1:
                raise RuntimeError("transcription failed")

            return TranscriptionResult(
                text="text",
                language="en",
                confidence=None,
                start=segment.timestamp,
                end=segment.timestamp + segment.duration,
            )

    transcriber = FailingTranscriber()
    results: list[SourcedTranscriptionResult] = []

    executor = TranscriptionExecutorImpl(
        transcribers=(transcriber,),
        on_result=results.append,
        queue_capacity=10,
    )

    await executor.start()

    assert executor.submit(create_transcription_work_item(timestamp=0.0)) is True
    assert executor.submit(create_transcription_work_item(timestamp=1.0)) is True

    await executor.stop()

    assert transcriber.calls == 2
    assert len(results) == 1


@pytest.mark.anyio
async def test_executor_stop_drains_accepted_segments() -> None:
    transcriber = FakeTranscriber()
    results: list[SourcedTranscriptionResult] = []

    executor = TranscriptionExecutorImpl(
        transcribers=(transcriber,),
        on_result=results.append,
        queue_capacity=10,
    )

    await executor.start()

    items = [
        create_transcription_work_item(timestamp=0.0),
        create_transcription_work_item(timestamp=1.0),
        create_transcription_work_item(timestamp=2.0),
    ]

    segments = [item.segment for item in items]

    for item in items:
        assert executor.submit(item) is True

    await executor.stop()

    assert transcriber.transcribed == segments
    assert len(results) == 3


@pytest.mark.anyio
async def test_executor_stats_track_accepted_submissions() -> None:
    executor = TranscriptionExecutorImpl(
        transcribers=(FakeTranscriber(),),
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

    class BlockingTranscriber:
        def transcribe(self, segment: SpeechSegment) -> TranscriptionResult:
            started.set()
            release.wait()

            return TranscriptionResult(
                text="text",
                language="en",
                confidence=None,
                start=segment.timestamp,
                end=segment.timestamp + segment.duration,
            )

    executor = TranscriptionExecutorImpl(
        transcribers=(BlockingTranscriber(),),
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
    transcriber = FakeTranscriber()

    executor = TranscriptionExecutorImpl(
        transcribers=(transcriber,),
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
    class FailingTranscriber:
        def __init__(self) -> None:
            self.calls = 0

        def transcribe(self, segment: SpeechSegment) -> TranscriptionResult:
            self.calls += 1

            if self.calls <= 2:
                raise RuntimeError("transcription failed")

            return TranscriptionResult(
                text="text",
                language="en",
                confidence=None,
                start=segment.timestamp,
                end=segment.timestamp + segment.duration,
            )

    executor = TranscriptionExecutorImpl(
        transcribers=(FailingTranscriber(),),
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

    class BlockingTranscriber:
        def transcribe(self, segment: SpeechSegment) -> TranscriptionResult:
            started.set()
            release.wait()

            return TranscriptionResult(
                text="text",
                language="en",
                confidence=None,
                start=segment.timestamp,
                end=segment.timestamp + segment.duration,
            )

    executor = TranscriptionExecutorImpl(
        transcribers=(BlockingTranscriber(),),
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
        transcribers=(FakeTranscriber(),),
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
    transcriber = FakeTranscriber()
    results: list[SourcedTranscriptionResult] = []

    executor = TranscriptionExecutorImpl(
        transcribers=(transcriber,),
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
    transcriber = FakeTranscriber()
    results: list[SourcedTranscriptionResult] = []

    executor = TranscriptionExecutorImpl(
        transcribers=(transcriber,),
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


def test_executor_requires_at_least_one_transcriber() -> None:
    with pytest.raises(
        ValueError,
        match="at least one transcriber is required",
    ):
        TranscriptionExecutorImpl(
            transcribers=(),
            on_result=lambda _: None,
            queue_capacity=10,
        )


def test_executor_initial_concurrency_stats() -> None:
    # Arrange
    executor = TranscriptionExecutorImpl(
        transcribers=(FakeTranscriber(),),
        on_result=lambda _: None,
        queue_capacity=10,
    )

    stats = executor.stats

    # Assert
    assert stats.worker_count == 1
    assert stats.active_workers == 0
    assert stats.active_workers_high_water_mark == 0


@pytest.mark.anyio
async def test_executor_processes_two_transcriptions_concurrently() -> None:
    first_started = threading.Event()
    second_started = threading.Event()
    release = threading.Event()

    class BlockingTranscriber:
        def __init__(self, started: threading.Event) -> None:
            self._started = started
            self.calls = 0

        def transcribe(
            self,
            segment: SpeechSegment,
        ) -> TranscriptionResult:
            self.calls += 1
            self._started.set()
            release.wait()

            return TranscriptionResult(
                text="text",
                language="en",
                confidence=None,
                start=segment.timestamp,
                end=segment.timestamp + segment.duration,
            )

    first = BlockingTranscriber(first_started)
    second = BlockingTranscriber(second_started)

    executor = TranscriptionExecutorImpl(
        transcribers=(first, second),
        on_result=lambda _: None,
        queue_capacity=10,
    )

    await executor.start()

    assert executor.submit(
        create_transcription_work_item(timestamp=0.0),
    )
    assert executor.submit(
        create_transcription_work_item(timestamp=1.0),
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
    class SelectiveTranscriber:
        def transcribe(
            self,
            segment: SpeechSegment,
        ) -> TranscriptionResult:
            if int(segment.timestamp) % 2 == 0:
                raise RuntimeError("transcription failed")

            return TranscriptionResult(
                text="text",
                language="en",
                confidence=None,
                start=segment.timestamp,
                end=segment.timestamp + segment.duration,
            )

    executor = TranscriptionExecutorImpl(
        transcribers=(
            SelectiveTranscriber(),
            SelectiveTranscriber(),
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
        transcribers=(
            FakeTranscriber(),
            FakeTranscriber(),
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
        transcribers=(
            FakeTranscriber(),
            FakeTranscriber(),
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
async def test_executor_allows_results_to_complete_out_of_submission_order() -> None:
    first_started = threading.Event()
    second_started = threading.Event()

    release_first = threading.Event()
    release_second = threading.Event()

    results: list[SourcedTranscriptionResult] = []
    second_completed = asyncio.Event()

    class ControlledTranscriber:
        def transcribe(
            self,
            segment: SpeechSegment,
        ) -> TranscriptionResult:
            if segment.timestamp == 0.0:
                first_started.set()
                release_first.wait()
            else:
                second_started.set()
                release_second.wait()

            return TranscriptionResult(
                text="text",
                language="en",
                confidence=None,
                start=segment.timestamp,
                end=segment.timestamp + segment.duration,
            )

    def handle_result(
        result: SourcedTranscriptionResult,
    ) -> None:
        results.append(result)

        if result.result.start == 1.0:
            second_completed.set()

    executor = TranscriptionExecutorImpl(
        transcribers=(
            ControlledTranscriber(),
            ControlledTranscriber(),
        ),
        on_result=handle_result,
        queue_capacity=10,
    )

    await executor.start()

    assert executor.submit(
        create_transcription_work_item(timestamp=0.0),
    )
    assert executor.submit(
        create_transcription_work_item(timestamp=1.0),
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
        transcribers=(
            FakeTranscriber(),
            FakeTranscriber(),
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
        transcribers=(
            FakeTranscriber(),
            FakeTranscriber(),
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
        "worker_count=2 max_active_workers=2" in record.getMessage() for record in caplog.records
    )


@pytest.mark.anyio
async def test_cancelling_wait_does_not_cancel_executor_lifecycle() -> None:
    transcriber_started = threading.Event()
    release_transcriber = threading.Event()

    class BlockingTranscriber:
        def transcribe(
            self,
            segment: SpeechSegment,
        ) -> TranscriptionResult:
            transcriber_started.set()
            release_transcriber.wait()

            return TranscriptionResult(
                text="done",
                language="en",
                confidence=None,
                start=segment.timestamp,
                end=segment.timestamp + segment.duration,
            )

    results: list[SourcedTranscriptionResult] = []

    executor = TranscriptionExecutorImpl(
        transcribers=(BlockingTranscriber(),),
        on_result=results.append,
        queue_capacity=10,
    )

    await executor.start()

    assert executor.submit(
        create_transcription_work_item(timestamp=1.0),
    )

    await asyncio.to_thread(transcriber_started.wait)

    wait_task = asyncio.create_task(executor.wait())

    await asyncio.sleep(0)

    wait_task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await wait_task

    stop_task = asyncio.create_task(executor.stop())

    await asyncio.sleep(0)

    assert not stop_task.done()

    release_transcriber.set()

    await stop_task

    assert len(results) == 1
    assert executor.stats.submitted == 1
    assert executor.stats.completed == 1
    assert executor.stats.failed == 0
