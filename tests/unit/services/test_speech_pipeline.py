from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable

import numpy as np
import pytest

from app.audio.contracts import (
    AudioFormat,
    AudioFrame,
    ProcessingAudioFrame,
    SpeechEnd,
    SpeechSegment,
    SpeechStart,
)
from app.audio.protocols import AudioCapture, AudioNormalizer
from app.services.speech_pipeline import SpeechPipeline
from app.transcription.contracts import (
    AudioSource,
    TranscriptionSegmentAggregatorStats,
    TranscriptionWorkItem,
)
from app.vad.protocols import AudioVad, SpeechSegmentAssembler

SAMPLE_RATE = 16_000
CHANNELS = 1
FRAME_SAMPLES = 320
AUDIO_FORMAT = AudioFormat(
    sample_rate=16_000,
    channels=1,
    sample_type="int16",
)


class FakeAudioCapture:
    def __init__(self, frames: list[AudioFrame]) -> None:
        self._frames = frames
        self.started = False
        self.stopped = False
        self._discontinuity_handler: Callable[[], None] | None = None

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True

    async def frames(self) -> AsyncIterator[AudioFrame]:
        for frame in self._frames:
            yield frame

    def set_discontinuity_handler(
        self,
        handler: Callable[[], None],
    ) -> None:
        self._discontinuity_handler = handler

    def signal_discontinuity(self) -> None:
        if self._discontinuity_handler is None:
            raise AssertionError("discontinuity handler was not registered")

        self._discontinuity_handler()


class ControllableAudioCapture(FakeAudioCapture):
    def __init__(self) -> None:
        super().__init__([])
        self._queue: asyncio.Queue[AudioFrame | None] = asyncio.Queue()

    async def frames(self) -> AsyncIterator[AudioFrame]:
        while True:
            frame = await self._queue.get()

            if frame is None:
                return

            yield frame

    async def submit(self, frame: AudioFrame) -> None:
        await self._queue.put(frame)

    async def close(self) -> None:
        await self._queue.put(None)


class FakeNormalizer:
    def __init__(
        self,
        processing_frames: tuple[ProcessingAudioFrame, ...],
        flushed_frames: tuple[ProcessingAudioFrame, ...] = (),
        events: list[str] | None = None,
    ) -> None:
        self.processing_frames = processing_frames
        self.flushed_frames = flushed_frames
        self.events = events

        self.processed: list[AudioFrame] = []
        self.flush_called = False
        self.reset_count = 0

    def process(
        self,
        frame: AudioFrame,
    ) -> tuple[ProcessingAudioFrame, ...]:
        self.processed.append(frame)

        if self.events is not None:
            self.events.append("normalizer-process")

        return self.processing_frames

    def flush(self) -> tuple[ProcessingAudioFrame, ...]:
        self.flush_called = True
        return self.flushed_frames

    def reset(self) -> None:
        self.reset_count += 1

        if self.events is not None:
            self.events.append("normalizer-reset")


class SequentialFakeNormalizer:
    def __init__(
        self,
        processing_frames: tuple[ProcessingAudioFrame, ...],
    ) -> None:
        self._processing_frames = iter(processing_frames)
        self.reset_count = 0

    def process(
        self,
        frame: AudioFrame,
    ) -> tuple[ProcessingAudioFrame, ...]:
        return (next(self._processing_frames),)

    def flush(self) -> tuple[ProcessingAudioFrame, ...]:
        return ()

    def reset(self) -> None:
        self.reset_count += 1


class FakeVad:
    def __init__(
        self,
        events: list[str] | None = None,
    ) -> None:
        self.processed: list[ProcessingAudioFrame] = []
        self.reset_count = 0
        self.events = events

    def process(
        self,
        frame: ProcessingAudioFrame,
    ) -> tuple[SpeechStart | SpeechEnd, ...]:
        self.processed.append(frame)

        if self.events is not None:
            self.events.append("vad-process")

        return ()

    def reset(self) -> None:
        self.reset_count += 1

        if self.events is not None:
            self.events.append("vad-reset")


class FakeAssembler:
    def __init__(
        self,
        segments_by_frame: dict[int, tuple[SpeechSegment, ...]],
        events: list[str] | None = None,
    ) -> None:
        self._segments_by_frame = segments_by_frame
        self.processed: list[ProcessingAudioFrame] = []
        self.reset_count = 0
        self.events = events

    def process(
        self,
        frame: ProcessingAudioFrame,
        events: tuple[SpeechStart | SpeechEnd, ...],
    ) -> tuple[SpeechSegment, ...]:
        self.processed.append(frame)

        if self.events is not None:
            self.events.append("assembler-process")

        return self._segments_by_frame.get(id(frame), ())

    def reset(self) -> None:
        self.reset_count += 1

        if self.events is not None:
            self.events.append("assembler-reset")

    def flush(self) -> tuple[SpeechSegment, ...]:
        return ()


class FakeTranscriptionSegmentAggregator:
    def __init__(self) -> None:
        self.processed: list[SpeechSegment] = []
        self.advanced: list[float] = []
        self.flush_calls = 0

        self.process_results: dict[
            int,
            tuple[SpeechSegment, ...],
        ] = {}

        self.advance_results: dict[
            float,
            tuple[SpeechSegment, ...],
        ] = {}

        self.flush_result: tuple[SpeechSegment, ...] = ()

        self.stats_result = TranscriptionSegmentAggregatorStats(
            segments_received=0,
            segments_emitted=0,
            segments_combined=0,
            output_seconds_total=0.0,
            output_seconds_max=0.0,
        )

    @property
    def stats(self) -> TranscriptionSegmentAggregatorStats:
        return self.stats_result

    def process(
        self,
        segment: SpeechSegment,
    ) -> tuple[SpeechSegment, ...]:
        self.processed.append(segment)
        return self.process_results.get(id(segment), ())

    def advance(
        self,
        timestamp: float,
    ) -> tuple[SpeechSegment, ...]:
        self.advanced.append(timestamp)
        return self.advance_results.get(timestamp, ())

    def flush(self) -> tuple[SpeechSegment, ...]:
        self.flush_calls += 1

        result = self.flush_result
        self.flush_result = ()

        return result


class PassThroughTranscriptionSegmentAggregator(FakeTranscriptionSegmentAggregator):
    def process(
        self,
        segment: SpeechSegment,
    ) -> tuple[SpeechSegment, ...]:
        self.processed.append(segment)
        return (segment,)


class FakeTranscriptionAudioPreprocessor:
    def __init__(
        self,
        result: SpeechSegment | None = None,
    ) -> None:
        self.result = result
        self.received: list[SpeechSegment] = []

    def process(
        self,
        segment: SpeechSegment,
    ) -> SpeechSegment:
        self.received.append(segment)

        if self.result is None:
            return segment

        return self.result


class FakeTranscriptionExecutor:
    def __init__(self) -> None:
        self.attempted: list[TranscriptionWorkItem] = []
        self.submitted: list[TranscriptionWorkItem] = []
        self.accept = True
        self.started = False
        self.stopped = False

    async def start(self) -> None:
        self.started = True

    def submit(self, item: TranscriptionWorkItem) -> bool:
        self.attempted.append(item)

        if not self.accept:
            return False

        self.submitted.append(item)
        return True

    async def stop(self) -> None:
        self.stopped = True

    async def wait(self) -> None:
        """Wait until an executor worker terminates unexpectedly."""


def create_audio_frame() -> AudioFrame:
    audio = np.full(
        (FRAME_SAMPLES, CHANNELS),
        1.0,
        dtype=np.int16,
    )
    return AudioFrame(
        audio=audio,
        timestamp=1.0,
        format=AUDIO_FORMAT,
    )


def create_processing_frame(
    value: float | None = None,
    *,
    timestamp: float = 0.020,
) -> ProcessingAudioFrame:
    frame_value = 1.0 if value is None else value

    audio = np.full(
        (FRAME_SAMPLES, CHANNELS),
        frame_value,
        dtype=np.float32,
    )

    return ProcessingAudioFrame(
        audio=audio,
        timestamp=timestamp,
        format=AudioFormat(
            sample_rate=16_000,
            channels=1,
            sample_type="float32",
        ),
    )


def create_speech_segment(
    *,
    timestamp: float = 10.0,
    duration: float = 1.0,
    value: float = 1.0,
) -> SpeechSegment:
    sample_count = round(duration * SAMPLE_RATE)

    audio = np.full(
        (sample_count, 1),
        value,
        dtype=np.float32,
    )

    return SpeechSegment(
        audio=audio,
        timestamp=timestamp,
        duration=sample_count / SAMPLE_RATE,
        format=AUDIO_FORMAT,
    )


def create_transcription_work_item(
    source: AudioSource = AudioSource.SYSTEM_AUDIO,
) -> TranscriptionWorkItem:
    return TranscriptionWorkItem(source=source, segment=create_speech_segment())


def create_pipeline(
    *,
    capture: AudioCapture | None = None,
    normalizer: AudioNormalizer | None = None,
    vad: AudioVad | None = None,
    assembler: SpeechSegmentAssembler | None = None,
    transcription_segment_aggregator: FakeTranscriptionSegmentAggregator | None = None,
    transcription_preprocessor: FakeTranscriptionAudioPreprocessor | None = None,
    transcription_executor: FakeTranscriptionExecutor | None = None,
    processing_frames: tuple[ProcessingAudioFrame, ...] | None = None,
    segments: tuple[SpeechSegment, ...] = (),
    segments_by_frame: dict[int, tuple[SpeechSegment, ...]] | None = None,
    source: AudioSource = AudioSource.SYSTEM_AUDIO,
) -> SpeechPipeline:
    if processing_frames is None:
        processing_frames = (create_processing_frame(),)

    if capture is None:
        capture = FakeAudioCapture([create_audio_frame()])

    if normalizer is None:
        normalizer = FakeNormalizer(processing_frames)

    if vad is None:
        vad = FakeVad()

    if assembler is None:
        if segments_by_frame is not None:
            assembler_results = segments_by_frame
        else:
            assembler_results = {
                id(processing_frames[0]): segments,
            }

        assembler = FakeAssembler(assembler_results)

    if transcription_segment_aggregator is None:
        transcription_segment_aggregator = PassThroughTranscriptionSegmentAggregator()

    if transcription_preprocessor is None:
        transcription_preprocessor = FakeTranscriptionAudioPreprocessor()

    if transcription_executor is None:
        transcription_executor = FakeTranscriptionExecutor()

    return SpeechPipeline(
        source=source,
        capture=capture,
        normalizer=normalizer,
        vad=vad,
        assembler=assembler,
        transcription_segment_aggregator=transcription_segment_aggregator,
        transcription_audio_preprocessor=transcription_preprocessor,
        transcription_executor=transcription_executor,
    )


@pytest.mark.anyio
async def test_pipeline_processes_frame_through_all_stages() -> None:
    # Arrange
    captured_frame = create_audio_frame()
    processing_frame = create_processing_frame()
    item = create_transcription_work_item()

    capture = FakeAudioCapture([captured_frame])
    normalizer = FakeNormalizer((processing_frame,))
    vad = FakeVad()
    assembler = FakeAssembler(
        {
            id(processing_frame): (item.segment,),
        }
    )
    transcription_executor = FakeTranscriptionExecutor()

    pipeline = SpeechPipeline(
        source=AudioSource.SYSTEM_AUDIO,
        capture=capture,
        normalizer=normalizer,
        vad=vad,
        assembler=assembler,
        transcription_segment_aggregator=PassThroughTranscriptionSegmentAggregator(),
        transcription_audio_preprocessor=FakeTranscriptionAudioPreprocessor(),
        transcription_executor=transcription_executor,
    )

    # Act
    await pipeline.start()

    # Give the processing task an opportunity to consume the frame.
    await asyncio.sleep(0)

    await pipeline.stop()

    # Assert
    assert capture.started
    assert normalizer.processed == [captured_frame]
    assert vad.processed == [processing_frame]
    assert assembler.processed == [processing_frame]
    assert transcription_executor.submitted == [item]


@pytest.mark.anyio
async def test_pipeline_processes_all_normalized_frames() -> None:
    captured_frame = create_audio_frame()

    processing_frames = (
        create_processing_frame(),
        create_processing_frame(),
        create_processing_frame(),
    )

    capture = FakeAudioCapture([captured_frame])
    normalizer = FakeNormalizer(processing_frames)
    vad = FakeVad()
    assembler = FakeAssembler({})
    transcription_executor = FakeTranscriptionExecutor()

    pipeline = SpeechPipeline(
        source=AudioSource.SYSTEM_AUDIO,
        capture=capture,
        normalizer=normalizer,
        vad=vad,
        assembler=assembler,
        transcription_segment_aggregator=PassThroughTranscriptionSegmentAggregator(),
        transcription_audio_preprocessor=FakeTranscriptionAudioPreprocessor(),
        transcription_executor=transcription_executor,
    )

    await pipeline.start()
    await asyncio.sleep(0)
    await pipeline.stop()

    assert vad.processed == list(processing_frames)
    assert assembler.processed == list(processing_frames)


@pytest.mark.anyio
async def test_pipeline_submits_all_items_from_one_processing_frame() -> None:
    processing_frame = create_processing_frame()

    item_one = create_transcription_work_item()
    item_two = create_transcription_work_item()

    capture = FakeAudioCapture([create_audio_frame()])
    normalizer = FakeNormalizer((processing_frame,))
    vad = FakeVad()
    assembler = FakeAssembler(
        {
            id(processing_frame): (
                item_one.segment,
                item_two.segment,
            ),
        }
    )
    transcription_executor = FakeTranscriptionExecutor()

    pipeline = SpeechPipeline(
        source=AudioSource.SYSTEM_AUDIO,
        capture=capture,
        normalizer=normalizer,
        vad=vad,
        assembler=assembler,
        transcription_segment_aggregator=PassThroughTranscriptionSegmentAggregator(),
        transcription_audio_preprocessor=FakeTranscriptionAudioPreprocessor(),
        transcription_executor=transcription_executor,
    )

    await pipeline.start()
    await pipeline.wait()

    assert transcription_executor.submitted == [
        item_one,
        item_two,
    ]


@pytest.mark.anyio
async def test_pipeline_processes_frames_emitted_by_normalizer_flush() -> None:
    captured_frame = create_audio_frame()
    flushed_frame = create_processing_frame()

    capture = FakeAudioCapture([captured_frame])
    normalizer = FakeNormalizer(
        processing_frames=(),
        flushed_frames=(flushed_frame,),
    )
    vad = FakeVad()
    assembler = FakeAssembler({})
    transcription_executor = FakeTranscriptionExecutor()

    pipeline = SpeechPipeline(
        source=AudioSource.SYSTEM_AUDIO,
        capture=capture,
        normalizer=normalizer,
        vad=vad,
        assembler=assembler,
        transcription_segment_aggregator=PassThroughTranscriptionSegmentAggregator(),
        transcription_audio_preprocessor=FakeTranscriptionAudioPreprocessor(),
        transcription_executor=transcription_executor,
    )

    await pipeline.start()
    await asyncio.sleep(0)
    await pipeline.stop()

    assert normalizer.flush_called
    assert vad.processed == [flushed_frame]


@pytest.mark.anyio
async def test_stop_stops_capture() -> None:
    capture = FakeAudioCapture([])

    pipeline = create_pipeline(capture=capture)

    await pipeline.start()
    await pipeline.stop()

    assert capture.stopped


@pytest.mark.anyio
async def test_stop_before_start_is_harmless() -> None:
    capture = FakeAudioCapture([])

    pipeline = create_pipeline(capture=capture)

    await pipeline.stop()

    assert not capture.started
    assert not capture.stopped


@pytest.mark.anyio
async def test_stop_is_idempotent() -> None:
    capture = FakeAudioCapture([])

    pipeline = create_pipeline(capture=capture)

    await pipeline.start()

    await pipeline.stop()
    await pipeline.stop()

    assert capture.stopped


@pytest.mark.anyio
async def test_start_twice_raises() -> None:
    pipeline = create_pipeline()

    await pipeline.start()

    with pytest.raises(RuntimeError, match="already been started"):
        await pipeline.start()

    await pipeline.stop()


@pytest.mark.anyio
async def test_stop_discards_incomplete_assembler_state() -> None:
    assembler = FakeAssembler({})

    pipeline = create_pipeline(
        assembler=assembler,
    )

    await pipeline.start()
    await pipeline.stop()

    assert assembler.reset_count == 1


@pytest.mark.anyio
async def test_wait_before_start_is_harmless() -> None:
    pipeline = create_pipeline()

    await pipeline.wait()


@pytest.mark.anyio
async def test_pipeline_discontinuity_callback_only_marks_pending_reset() -> None:
    # Arrange
    capture = ControllableAudioCapture()

    normalizer = FakeNormalizer(())
    vad = FakeVad()
    assembler = FakeAssembler({})
    transcription_executor = FakeTranscriptionExecutor()

    pipeline = SpeechPipeline(
        source=AudioSource.SYSTEM_AUDIO,
        capture=capture,
        normalizer=normalizer,
        vad=vad,
        assembler=assembler,
        transcription_segment_aggregator=PassThroughTranscriptionSegmentAggregator(),
        transcription_audio_preprocessor=FakeTranscriptionAudioPreprocessor(),
        transcription_executor=transcription_executor,
    )

    await pipeline.start()

    # Act
    capture.signal_discontinuity()

    # Assert
    assert normalizer.reset_count == 0
    assert vad.reset_count == 0
    assert assembler.reset_count == 0

    await capture.close()
    await pipeline.wait()


@pytest.mark.anyio
async def test_pipeline_discontinuity_resets_processing_components() -> None:
    # Arrange
    capture = ControllableAudioCapture()

    processing_frame = create_processing_frame()

    normalizer = FakeNormalizer((processing_frame,))
    vad = FakeVad()
    assembler = FakeAssembler({})
    transcription_executor = FakeTranscriptionExecutor()

    pipeline = SpeechPipeline(
        source=AudioSource.SYSTEM_AUDIO,
        capture=capture,
        normalizer=normalizer,
        vad=vad,
        assembler=assembler,
        transcription_segment_aggregator=PassThroughTranscriptionSegmentAggregator(),
        transcription_audio_preprocessor=FakeTranscriptionAudioPreprocessor(),
        transcription_executor=transcription_executor,
    )

    await pipeline.start()

    capture.signal_discontinuity()

    # Act
    await capture.submit(create_audio_frame())

    await asyncio.sleep(0)

    # Assert
    assert normalizer.reset_count == 1
    assert vad.reset_count == 1
    assert assembler.reset_count == 1

    await capture.close()
    await pipeline.wait()


@pytest.mark.anyio
async def test_pipeline_resets_before_first_post_discontinuity_frame() -> None:
    # Arrange
    events: list[str] = []

    capture = ControllableAudioCapture()
    processing_frame = create_processing_frame()

    normalizer = FakeNormalizer(
        (processing_frame,),
        events=events,
    )
    vad = FakeVad()
    vad.events = events

    assembler = FakeAssembler({})
    assembler.events = events
    transcription_executor = FakeTranscriptionExecutor()

    pipeline = SpeechPipeline(
        source=AudioSource.SYSTEM_AUDIO,
        capture=capture,
        normalizer=normalizer,
        vad=vad,
        assembler=assembler,
        transcription_segment_aggregator=PassThroughTranscriptionSegmentAggregator(),
        transcription_audio_preprocessor=FakeTranscriptionAudioPreprocessor(),
        transcription_executor=transcription_executor,
    )

    await pipeline.start()

    capture.signal_discontinuity()

    # Act
    await capture.submit(create_audio_frame())

    await asyncio.sleep(0)

    # Assert
    assert events == [
        "normalizer-reset",
        "vad-reset",
        "assembler-reset",
        "normalizer-process",
        "vad-process",
        "assembler-process",
    ]

    await capture.close()
    await pipeline.wait()


@pytest.mark.anyio
async def test_pipeline_handles_multiple_discontinuities() -> None:
    # Arrange
    capture = ControllableAudioCapture()
    processing_frame = create_processing_frame()

    normalizer = FakeNormalizer((processing_frame,))
    vad = FakeVad()
    assembler = FakeAssembler({})
    transcription_executor = FakeTranscriptionExecutor()

    pipeline = SpeechPipeline(
        source=AudioSource.SYSTEM_AUDIO,
        capture=capture,
        normalizer=normalizer,
        vad=vad,
        assembler=assembler,
        transcription_segment_aggregator=PassThroughTranscriptionSegmentAggregator(),
        transcription_audio_preprocessor=FakeTranscriptionAudioPreprocessor(),
        transcription_executor=transcription_executor,
    )

    await pipeline.start()

    # Act
    capture.signal_discontinuity()
    await capture.submit(create_audio_frame())
    await asyncio.sleep(0)

    capture.signal_discontinuity()
    await capture.submit(create_audio_frame())
    await asyncio.sleep(0)

    # Assert
    assert normalizer.reset_count == 2
    assert vad.reset_count == 2
    assert assembler.reset_count == 2

    await capture.close()
    await pipeline.wait()


@pytest.mark.anyio
async def test_pipeline_coalesces_multiple_pending_discontinuities() -> None:
    # Arrange
    capture = ControllableAudioCapture()
    processing_frame = create_processing_frame()

    normalizer = FakeNormalizer((processing_frame,))
    vad = FakeVad()
    assembler = FakeAssembler({})
    transcription_executor = FakeTranscriptionExecutor()

    pipeline = SpeechPipeline(
        source=AudioSource.SYSTEM_AUDIO,
        capture=capture,
        normalizer=normalizer,
        vad=vad,
        assembler=assembler,
        transcription_segment_aggregator=PassThroughTranscriptionSegmentAggregator(),
        transcription_audio_preprocessor=FakeTranscriptionAudioPreprocessor(),
        transcription_executor=transcription_executor,
    )

    await pipeline.start()

    # Act
    capture.signal_discontinuity()
    capture.signal_discontinuity()
    capture.signal_discontinuity()

    await capture.submit(create_audio_frame())
    await asyncio.sleep(0)

    # Assert
    assert normalizer.reset_count == 1
    assert vad.reset_count == 1
    assert assembler.reset_count == 1

    await capture.close()
    await pipeline.wait()


@pytest.mark.anyio
async def test_pipeline_discontinuity_does_not_submit_transcription() -> None:
    # Arrange
    capture = ControllableAudioCapture()

    normalizer = FakeNormalizer(())
    vad = FakeVad()
    assembler = FakeAssembler({})
    transcription_executor = FakeTranscriptionExecutor()

    pipeline = SpeechPipeline(
        source=AudioSource.SYSTEM_AUDIO,
        capture=capture,
        normalizer=normalizer,
        vad=vad,
        assembler=assembler,
        transcription_segment_aggregator=PassThroughTranscriptionSegmentAggregator(),
        transcription_audio_preprocessor=FakeTranscriptionAudioPreprocessor(),
        transcription_executor=transcription_executor,
    )

    await pipeline.start()

    # Act
    capture.signal_discontinuity()
    await asyncio.sleep(0)

    # Assert
    assert transcription_executor.submitted == []

    await capture.close()
    await pipeline.wait()


@pytest.mark.anyio
async def test_pipeline_logs_vad_segments_and_final_statistics(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Arrange
    processing_frame = create_processing_frame()
    segment = create_speech_segment()

    class VadWithEvents(FakeVad):
        def process(
            self,
            frame: ProcessingAudioFrame,
        ) -> tuple[SpeechStart | SpeechEnd, ...]:
            return (SpeechStart(timestamp=12.0),)

    capture = FakeAudioCapture([create_audio_frame()])
    transcription_executor = FakeTranscriptionExecutor()
    aggregator = PassThroughTranscriptionSegmentAggregator()

    aggregator.stats_result = TranscriptionSegmentAggregatorStats(
        segments_received=3,
        segments_emitted=2,
        segments_combined=1,
        output_seconds_total=8.0,
        output_seconds_max=5.0,
    )

    pipeline = SpeechPipeline(
        source=AudioSource.SYSTEM_AUDIO,
        capture=capture,
        normalizer=FakeNormalizer((processing_frame,)),
        vad=VadWithEvents(),
        assembler=FakeAssembler({id(processing_frame): (segment,)}),
        transcription_segment_aggregator=aggregator,
        transcription_audio_preprocessor=FakeTranscriptionAudioPreprocessor(),
        transcription_executor=transcription_executor,
    )

    # Act
    with caplog.at_level("INFO", logger="app.services.speech_pipeline"):
        await pipeline.start()
        await pipeline.wait()
        await pipeline.stop()

    # Assert
    messages = [record.getMessage() for record in caplog.records]
    assert any(
        "VAD SpeechStart source=system_audio timestamp=12.000" in message for message in messages
    )
    assert any("speech segment emitted source=system_audio id=1" in message for message in messages)
    assert any(
        "speech pipeline stopped source=system_audio "
        "captured_frames=1 processing_frames=1 "
        "segments_emitted=1 segments_rejected=0 "
        "short_segments=0 avg_segment_duration=1.000 "
        "max_segment_duration=1.000 "
        "aggregation_received=3 aggregation_emitted=2 "
        "aggregation_combined=1 avg_aggregate_duration=4.000 "
        "max_aggregate_duration=5.000" in message
        for message in messages
    )


@pytest.mark.anyio
async def test_pipeline_continues_when_transcription_executor_rejects_item() -> None:
    processing_frame = create_processing_frame()
    item = create_transcription_work_item()

    transcription_executor = FakeTranscriptionExecutor()
    transcription_executor.accept = False

    pipeline = SpeechPipeline(
        source=AudioSource.SYSTEM_AUDIO,
        capture=FakeAudioCapture([create_audio_frame()]),
        normalizer=FakeNormalizer((processing_frame,)),
        vad=FakeVad(),
        assembler=FakeAssembler(
            {id(processing_frame): (item.segment,)},
        ),
        transcription_segment_aggregator=PassThroughTranscriptionSegmentAggregator(),
        transcription_audio_preprocessor=FakeTranscriptionAudioPreprocessor(),
        transcription_executor=transcription_executor,
    )

    await pipeline.start()
    await pipeline.wait()

    assert transcription_executor.attempted == [item]
    assert transcription_executor.submitted == []


@pytest.mark.anyio
async def test_pipeline_counts_rejected_transcription_item(
    caplog: pytest.LogCaptureFixture,
) -> None:
    item = create_transcription_work_item()

    executor = FakeTranscriptionExecutor()
    executor.accept = False

    pipeline = create_pipeline(
        transcription_executor=executor,
        segments=(item.segment,),
    )

    with caplog.at_level("INFO", logger="app.services.speech_pipeline"):
        await pipeline.start()
        await pipeline.wait()
        await pipeline.stop()

    assert executor.attempted == [item]
    assert executor.submitted == []

    messages = [record.getMessage() for record in caplog.records]

    assert any("segments_emitted=1 segments_rejected=1" in message for message in messages)


@pytest.mark.anyio
async def test_pipeline_does_not_deliver_rejected_segment() -> None:
    item = create_transcription_work_item()

    executor = FakeTranscriptionExecutor()
    executor.accept = False

    pipeline = create_pipeline(
        transcription_executor=executor,
        segments=(item.segment,),
    )

    await pipeline.start()
    await pipeline.wait()

    assert executor.attempted == [item]
    assert executor.submitted == []


@pytest.mark.anyio
async def test_pipeline_continues_after_transcription_rejection() -> None:
    processing_frame_one = create_processing_frame(1.0)
    processing_frame_two = create_processing_frame(2.0)

    item_one = create_transcription_work_item()
    item_two = create_transcription_work_item()

    class RejectFirstExecutor(FakeTranscriptionExecutor):
        def submit(self, item: TranscriptionWorkItem) -> bool:
            self.attempted.append(item)

            if len(self.attempted) == 1:
                return False

            self.submitted.append(item)
            return True

    executor = RejectFirstExecutor()

    capture = FakeAudioCapture(
        [
            create_audio_frame(),
            create_audio_frame(),
        ],
    )

    normalizer = SequentialFakeNormalizer(
        (
            processing_frame_one,
            processing_frame_two,
        ),
    )

    assembler = FakeAssembler(
        {
            id(processing_frame_one): (item_one.segment,),
            id(processing_frame_two): (item_two.segment,),
        },
    )

    pipeline = SpeechPipeline(
        source=AudioSource.SYSTEM_AUDIO,
        capture=capture,
        normalizer=normalizer,
        vad=FakeVad(),
        assembler=assembler,
        transcription_segment_aggregator=PassThroughTranscriptionSegmentAggregator(),
        transcription_audio_preprocessor=FakeTranscriptionAudioPreprocessor(),
        transcription_executor=executor,
    )

    await pipeline.start()
    await pipeline.wait()

    assert executor.attempted == [
        item_one,
        item_two,
    ]

    assert executor.submitted == [
        item_two,
    ]


@pytest.mark.anyio
async def test_pipeline_reports_rejected_segments_in_final_statistics(
    caplog: pytest.LogCaptureFixture,
) -> None:
    item_one = create_transcription_work_item()
    item_two = create_transcription_work_item()

    class RejectFirstExecutor(FakeTranscriptionExecutor):
        def submit(self, item: TranscriptionWorkItem) -> bool:
            self.attempted.append(item)

            if len(self.attempted) == 1:
                return False

            self.submitted.append(item)
            return True

    executor = RejectFirstExecutor()

    processing_frame_one = create_processing_frame(1.0)
    processing_frame_two = create_processing_frame(2.0)

    pipeline = SpeechPipeline(
        source=AudioSource.SYSTEM_AUDIO,
        capture=FakeAudioCapture(
            [
                create_audio_frame(),
                create_audio_frame(),
            ],
        ),
        normalizer=SequentialFakeNormalizer(
            (
                processing_frame_one,
                processing_frame_two,
            ),
        ),
        vad=FakeVad(),
        assembler=FakeAssembler(
            {
                id(processing_frame_one): (item_one.segment,),
                id(processing_frame_two): (item_two.segment,),
            },
        ),
        transcription_segment_aggregator=PassThroughTranscriptionSegmentAggregator(),
        transcription_audio_preprocessor=FakeTranscriptionAudioPreprocessor(),
        transcription_executor=executor,
    )

    with caplog.at_level("INFO", logger="app.services.speech_pipeline"):
        await pipeline.start()
        await pipeline.wait()
        await pipeline.stop()

    messages = [record.getMessage() for record in caplog.records]

    assert any("segments_emitted=2 segments_rejected=1" in message for message in messages)


@pytest.mark.anyio
async def test_pipeline_attaches_source_to_transcription_work_item() -> None:
    # Arrange
    processing_frame = create_processing_frame()
    segment = create_speech_segment()

    transcription_executor = FakeTranscriptionExecutor()

    pipeline = SpeechPipeline(
        source=AudioSource.MICROPHONE,
        capture=FakeAudioCapture([create_audio_frame()]),
        normalizer=FakeNormalizer((processing_frame,)),
        vad=FakeVad(),
        assembler=FakeAssembler(
            {
                id(processing_frame): (segment,),
            }
        ),
        transcription_segment_aggregator=PassThroughTranscriptionSegmentAggregator(),
        transcription_audio_preprocessor=FakeTranscriptionAudioPreprocessor(),
        transcription_executor=transcription_executor,
    )

    # Act
    await pipeline.start()
    await pipeline.wait()
    await pipeline.stop()

    # Assert
    assert transcription_executor.submitted == [
        TranscriptionWorkItem(
            source=AudioSource.MICROPHONE,
            segment=segment,
        )
    ]


@pytest.mark.anyio
async def test_pipeline_does_not_manage_transcription_executor_lifecycle() -> None:
    # Arrange
    capture = FakeAudioCapture([])
    transcription_executor = FakeTranscriptionExecutor()

    pipeline = SpeechPipeline(
        source=AudioSource.SYSTEM_AUDIO,
        capture=capture,
        normalizer=FakeNormalizer(()),
        vad=FakeVad(),
        assembler=FakeAssembler({}),
        transcription_segment_aggregator=PassThroughTranscriptionSegmentAggregator(),
        transcription_audio_preprocessor=FakeTranscriptionAudioPreprocessor(),
        transcription_executor=transcription_executor,
    )

    # Act
    await pipeline.start()
    await pipeline.wait()
    await pipeline.stop()

    # Assert
    assert not transcription_executor.started
    assert not transcription_executor.stopped


@pytest.mark.anyio
async def test_pipeline_passes_assembler_segment_to_aggregator() -> None:
    # Arrange
    processing_frame = create_processing_frame(1.0)
    segment = create_speech_segment()

    aggregator = FakeTranscriptionSegmentAggregator()

    pipeline = create_pipeline(
        processing_frames=(processing_frame,),
        segments=(segment,),
        transcription_segment_aggregator=aggregator,
    )

    # Act
    await pipeline.start()
    await pipeline.wait()

    # Assert
    assert aggregator.processed == [segment]


@pytest.mark.anyio
async def test_pipeline_does_not_submit_buffered_semantic_segment() -> None:
    # Arrange
    processing_frame = create_processing_frame(1.0)
    segment = create_speech_segment()

    aggregator = FakeTranscriptionSegmentAggregator()
    aggregator.process_results[id(segment)] = ()

    executor = FakeTranscriptionExecutor()

    pipeline = create_pipeline(
        processing_frames=(processing_frame,),
        segments=(segment,),
        transcription_segment_aggregator=aggregator,
        transcription_executor=executor,
    )

    # Act
    await pipeline.start()
    await pipeline.wait()

    # Assert
    assert aggregator.processed == [segment]
    assert executor.attempted == []


@pytest.mark.anyio
async def test_pipeline_submits_segment_emitted_by_aggregator() -> None:
    # Arrange
    processing_frame = create_processing_frame(1.0)

    semantic_segment = create_speech_segment(
        timestamp=10.0,
        duration=1.0,
    )
    aggregated_segment = create_speech_segment(
        timestamp=10.0,
        duration=5.0,
    )

    aggregator = FakeTranscriptionSegmentAggregator()
    aggregator.process_results[id(semantic_segment)] = (aggregated_segment,)

    executor = FakeTranscriptionExecutor()

    pipeline = create_pipeline(
        processing_frames=(processing_frame,),
        segments=(semantic_segment,),
        transcription_segment_aggregator=aggregator,
        transcription_executor=executor,
    )

    # Act
    await pipeline.start()
    await pipeline.wait()

    # Assert
    assert executor.attempted == [
        TranscriptionWorkItem(
            source=AudioSource.SYSTEM_AUDIO,
            segment=aggregated_segment,
        )
    ]


@pytest.mark.anyio
async def test_pipeline_advances_aggregator_with_processing_timeline() -> None:
    # Arrange
    processing_frames = (
        create_processing_frame(1.0),
        create_processing_frame(2.0),
        create_processing_frame(3.0),
    )

    aggregator = FakeTranscriptionSegmentAggregator()

    pipeline = create_pipeline(
        processing_frames=processing_frames,
        transcription_segment_aggregator=aggregator,
    )

    # Act
    await pipeline.start()
    await pipeline.wait()

    # Assert
    assert aggregator.advanced == [frame.timestamp for frame in processing_frames]


@pytest.mark.anyio
async def test_pipeline_submits_segment_emitted_by_advance() -> None:
    # Arrange
    processing_frame = create_processing_frame(5.0)
    expired_segment = create_speech_segment(
        timestamp=1.0,
        duration=1.0,
    )

    aggregator = FakeTranscriptionSegmentAggregator()
    aggregator.advance_results[processing_frame.timestamp] = (expired_segment,)

    executor = FakeTranscriptionExecutor()

    pipeline = create_pipeline(
        processing_frames=(processing_frame,),
        transcription_segment_aggregator=aggregator,
        transcription_executor=executor,
    )

    # Act
    await pipeline.start()
    await pipeline.wait()

    # Assert
    assert executor.attempted == [
        TranscriptionWorkItem(
            source=AudioSource.SYSTEM_AUDIO,
            segment=expired_segment,
        )
    ]


@pytest.mark.anyio
async def test_pipeline_advances_aggregator_before_processing_new_segment() -> None:
    # Arrange
    events: list[str] = []
    processing_frame = create_processing_frame(5.0)
    segment = create_speech_segment()

    class RecordingAggregator(FakeTranscriptionSegmentAggregator):
        def advance(
            self,
            timestamp: float,
        ) -> tuple[SpeechSegment, ...]:
            events.append("advance")
            return super().advance(timestamp)

        def process(
            self,
            segment: SpeechSegment,
        ) -> tuple[SpeechSegment, ...]:
            events.append("process")
            return super().process(segment)

    aggregator = RecordingAggregator()

    pipeline = create_pipeline(
        processing_frames=(processing_frame,),
        segments=(segment,),
        transcription_segment_aggregator=aggregator,
    )

    # Act
    await pipeline.start()
    await pipeline.wait()

    # Assert
    assert events == [
        "advance",
        "process",
    ]


@pytest.mark.anyio
async def test_stop_submits_pending_aggregate() -> None:
    # Arrange
    pending_segment = create_speech_segment(
        timestamp=10.0,
        duration=1.0,
    )

    aggregator = FakeTranscriptionSegmentAggregator()
    aggregator.flush_result = (pending_segment,)

    executor = FakeTranscriptionExecutor()

    pipeline = create_pipeline(
        transcription_segment_aggregator=aggregator,
        transcription_executor=executor,
    )

    await pipeline.start()

    # Act
    await pipeline.stop()

    # Assert
    assert executor.attempted == [
        TranscriptionWorkItem(
            source=AudioSource.SYSTEM_AUDIO,
            segment=pending_segment,
        )
    ]


@pytest.mark.anyio
async def test_stop_handles_empty_aggregator_flush() -> None:
    # Arrange
    aggregator = FakeTranscriptionSegmentAggregator()
    executor = FakeTranscriptionExecutor()

    pipeline = create_pipeline(
        transcription_segment_aggregator=aggregator,
        transcription_executor=executor,
    )

    await pipeline.start()

    # Act
    await pipeline.stop()

    # Assert
    assert aggregator.flush_calls == 1
    assert executor.attempted == []


@pytest.mark.anyio
async def test_rejected_shutdown_aggregate_is_counted() -> None:
    # Arrange
    pending_segment = create_speech_segment(
        timestamp=10.0,
        duration=1.0,
    )

    aggregator = FakeTranscriptionSegmentAggregator()
    aggregator.flush_result = (pending_segment,)

    class RejectingExecutor(FakeTranscriptionExecutor):
        def submit(
            self,
            item: TranscriptionWorkItem,
        ) -> bool:
            self.attempted.append(item)
            return False

    executor = RejectingExecutor()

    pipeline = create_pipeline(
        transcription_segment_aggregator=aggregator,
        transcription_executor=executor,
    )

    await pipeline.start()

    # Act
    await pipeline.stop()

    # Assert
    assert pipeline.stats.segments_rejected == 1


@pytest.mark.anyio
async def test_repeated_stop_does_not_flush_aggregator_twice() -> None:
    # Arrange
    aggregator = FakeTranscriptionSegmentAggregator()

    pipeline = create_pipeline(
        transcription_segment_aggregator=aggregator,
    )

    await pipeline.start()

    # Act
    await pipeline.stop()
    await pipeline.stop()

    # Assert
    assert aggregator.flush_calls == 1


@pytest.mark.anyio
async def test_discontinuity_submits_pending_aggregate() -> None:
    # Arrange
    pending_segment = create_speech_segment(
        timestamp=10.0,
        duration=1.0,
    )

    aggregator = FakeTranscriptionSegmentAggregator()
    aggregator.flush_result = (pending_segment,)

    executor = FakeTranscriptionExecutor()
    capture = ControllableAudioCapture()

    pipeline = create_pipeline(
        capture=capture,
        transcription_segment_aggregator=aggregator,
        transcription_executor=executor,
    )

    await pipeline.start()

    capture.signal_discontinuity()

    # Act
    await capture.submit(create_audio_frame())
    await asyncio.sleep(0)

    # Assert
    assert executor.attempted == [
        TranscriptionWorkItem(
            source=AudioSource.SYSTEM_AUDIO,
            segment=pending_segment,
        )
    ]

    await capture.close()
    await pipeline.wait()


@pytest.mark.anyio
async def test_discontinuity_flushes_aggregator_before_processing_state_reset() -> None:
    # Arrange
    events: list[str] = []
    capture = ControllableAudioCapture()
    executor = FakeTranscriptionExecutor()

    class RecordingAggregator(FakeTranscriptionSegmentAggregator):
        def flush(self) -> tuple[SpeechSegment, ...]:
            events.append("aggregator-flush")
            return super().flush()

    class RecordingNormalizer(FakeNormalizer):
        def reset(self) -> None:
            events.append("normalizer-reset")
            super().reset()

    class RecordingVad(FakeVad):
        def reset(self) -> None:
            events.append("vad-reset")
            super().reset()

    class RecordingAssembler(FakeAssembler):
        def reset(self) -> None:
            events.append("assembler-reset")
            super().reset()

    pipeline = SpeechPipeline(
        source=AudioSource.SYSTEM_AUDIO,
        capture=capture,
        normalizer=RecordingNormalizer(()),
        vad=RecordingVad(),
        assembler=RecordingAssembler({}),
        transcription_segment_aggregator=RecordingAggregator(),
        transcription_audio_preprocessor=FakeTranscriptionAudioPreprocessor(),
        transcription_executor=executor,
    )

    await pipeline.start()

    capture.signal_discontinuity()

    # Act
    await capture.submit(create_audio_frame())
    await asyncio.sleep(0)

    # Assert
    assert events[:4] == [
        "aggregator-flush",
        "normalizer-reset",
        "vad-reset",
        "assembler-reset",
    ]

    await capture.close()
    await pipeline.wait()


@pytest.mark.anyio
async def test_pipeline_preprocessed_segment_boundary() -> None:
    # Arrange
    original_segment = create_speech_segment()
    processed_segment = create_speech_segment()

    executor = FakeTranscriptionExecutor()
    preprocessor = FakeTranscriptionAudioPreprocessor(
        processed_segment,
    )

    pipeline = create_pipeline(
        segments=(original_segment,),
        transcription_executor=executor,
        transcription_preprocessor=preprocessor,
    )

    # Act
    await pipeline.start()
    await pipeline.wait()

    # Assert
    assert preprocessor.received == [original_segment]
    assert executor.submitted[0].segment is processed_segment


@pytest.mark.anyio
async def test_pipeline_preprocesses_segment_before_submission() -> None:
    processing_frame = create_processing_frame()

    original_segment = create_speech_segment(
        timestamp=10.0,
        value=0.1,
    )
    processed_segment = create_speech_segment(
        timestamp=10.0,
        value=0.2,
    )

    preprocessor = FakeTranscriptionAudioPreprocessor(
        result=processed_segment,
    )
    executor = FakeTranscriptionExecutor()

    pipeline = create_pipeline(
        processing_frames=(processing_frame,),
        segments=(original_segment,),
        transcription_preprocessor=preprocessor,
        transcription_executor=executor,
    )

    await pipeline.start()
    await pipeline.wait()

    assert preprocessor.received == [
        original_segment,
    ]

    assert len(executor.submitted) == 1

    submitted = executor.submitted[0]

    assert submitted.source is AudioSource.SYSTEM_AUDIO
    assert submitted.segment is processed_segment
