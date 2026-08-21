from __future__ import annotations

import asyncio
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
        transcriber=transcriber,
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
        transcriber=transcriber,
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
        transcriber=BlockingTranscriber(),
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
        transcriber=BlockingTranscriber(),
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
        transcriber=BlockingTranscriber(),
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

    # 4. Prove the executor recovered: a new segment is now successfully accepted
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
        transcriber=transcriber,
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
        transcriber=transcriber,
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
async def test_executor_stop_is_safe_when_called_multiple_times() -> None:
    executor = TranscriptionExecutorImpl(
        transcriber=FakeTranscriber(),
        on_result=lambda _: None,
        queue_capacity=1,
    )

    await executor.stop()

    await executor.start()
    await executor.stop()
    await executor.stop()


@pytest.mark.anyio
async def test_executor_stats_track_accepted_submissions() -> None:
    executor = TranscriptionExecutorImpl(
        transcriber=FakeTranscriber(),
        on_result=lambda _: None,
        queue_capacity=10,
    )

    await executor.start()

    assert executor.submit(create_transcription_work_item(timestamp=0.0)) is True
    assert executor.submit(create_transcription_work_item(timestamp=1.0)) is True

    await executor.stop()

    stats = executor.stats

    assert stats.accepted == 2


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
        transcriber=BlockingTranscriber(),
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
        transcriber=transcriber,
        on_result=lambda _: None,
        queue_capacity=10,
    )

    await executor.start()

    assert executor.submit(create_transcription_work_item(timestamp=0.0)) is True
    assert executor.submit(create_transcription_work_item(timestamp=1.0)) is True
    assert executor.submit(create_transcription_work_item(timestamp=2.0)) is True

    await executor.stop()

    stats = executor.stats

    assert stats.accepted == 3
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
        transcriber=FailingTranscriber(),
        on_result=lambda _: None,
        queue_capacity=10,
    )

    await executor.start()

    assert executor.submit(create_transcription_work_item(timestamp=0.0)) is True
    assert executor.submit(create_transcription_work_item(timestamp=1.0)) is True
    assert executor.submit(create_transcription_work_item(timestamp=2.0)) is True

    await executor.stop()

    stats = executor.stats

    assert stats.accepted == 3
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
        transcriber=BlockingTranscriber(),
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

    assert stats.max_queue_depth == 3

    release.set()

    await executor.stop()


@pytest.mark.anyio
async def test_executor_stats_are_snapshot() -> None:
    executor = TranscriptionExecutorImpl(
        transcriber=FakeTranscriber(),
        on_result=lambda _: None,
        queue_capacity=10,
    )

    await executor.start()

    assert executor.submit(create_transcription_work_item()) is True

    stats_before = executor.stats

    assert stats_before.accepted == 1

    assert executor.submit(create_transcription_work_item(timestamp=1.0)) is True

    stats_after = executor.stats

    assert stats_before.accepted == 1
    assert stats_after.accepted == 2

    await executor.stop()


@pytest.mark.anyio
async def test_executor_preserves_source_on_results() -> None:
    transcriber = FakeTranscriber()
    results: list[SourcedTranscriptionResult] = []

    executor = TranscriptionExecutorImpl(
        transcriber=transcriber,
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
        transcriber=transcriber,
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
