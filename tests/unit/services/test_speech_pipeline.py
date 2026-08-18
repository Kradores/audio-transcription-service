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


class FakeTranscriptionExecutor:
    def __init__(self) -> None:
        self.attempted: list[SpeechSegment] = []
        self.submitted: list[SpeechSegment] = []
        self.accept = True
        self.started = False
        self.stopped = False

    async def start(self) -> None:
        self.started = True

    def submit(self, segment: SpeechSegment) -> bool:
        self.attempted.append(segment)

        if not self.accept:
            return False

        self.submitted.append(segment)
        return True

    async def stop(self) -> None:
        self.stopped = True


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
) -> ProcessingAudioFrame:
    frame_value = 1.0 if value is None else value

    audio = np.full(
        (FRAME_SAMPLES, CHANNELS),
        frame_value,
        dtype=np.float32,
    )

    return ProcessingAudioFrame(
        audio=audio,
        timestamp=1 * 0.020,
        format=AudioFormat(
            sample_rate=16_000,
            channels=1,
            sample_type="float32",
        ),
    )


def create_speech_segment() -> SpeechSegment:
    audio = np.full(
        (FRAME_SAMPLES, CHANNELS),
        1.0,
        dtype=np.float32,
    )

    return SpeechSegment(
        audio=audio,
        timestamp=10.0,
        duration=0.020,
        format=AUDIO_FORMAT,
    )


def create_pipeline(
    *,
    capture: AudioCapture | None = None,
    normalizer: AudioNormalizer | None = None,
    vad: AudioVad | None = None,
    assembler: SpeechSegmentAssembler | None = None,
    transcription_executor: FakeTranscriptionExecutor | None = None,
    segments: tuple[SpeechSegment, ...] = (),
) -> SpeechPipeline:
    processing_frame = create_processing_frame()

    if capture is None:
        capture = FakeAudioCapture([create_audio_frame()])

    if normalizer is None:
        normalizer = FakeNormalizer((processing_frame,))

    if vad is None:
        vad = FakeVad()

    if assembler is None:
        assembler = FakeAssembler(
            {
                id(processing_frame): segments,
            }
        )

    if transcription_executor is None:
        transcription_executor = FakeTranscriptionExecutor()

    return SpeechPipeline(
        capture=capture,
        normalizer=normalizer,
        vad=vad,
        assembler=assembler,
        transcription_executor=transcription_executor,
    )


@pytest.mark.anyio
async def test_pipeline_processes_frame_through_all_stages() -> None:
    # Arrange
    captured_frame = create_audio_frame()
    processing_frame = create_processing_frame()
    segment = create_speech_segment()

    capture = FakeAudioCapture([captured_frame])
    normalizer = FakeNormalizer((processing_frame,))
    vad = FakeVad()
    assembler = FakeAssembler(
        {
            id(processing_frame): (segment,),
        }
    )
    transcription_executor = FakeTranscriptionExecutor()

    pipeline = SpeechPipeline(
        capture=capture,
        normalizer=normalizer,
        vad=vad,
        assembler=assembler,
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
    assert transcription_executor.submitted == [segment]
    assert transcription_executor.started
    assert transcription_executor.stopped


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
        capture=capture,
        normalizer=normalizer,
        vad=vad,
        assembler=assembler,
        transcription_executor=transcription_executor,
    )

    await pipeline.start()
    await asyncio.sleep(0)
    await pipeline.stop()

    assert vad.processed == list(processing_frames)
    assert assembler.processed == list(processing_frames)


@pytest.mark.anyio
async def test_pipeline_submits_all_segments_from_one_processing_frame() -> None:
    processing_frame = create_processing_frame()

    segment_one = create_speech_segment()
    segment_two = create_speech_segment()

    capture = FakeAudioCapture([create_audio_frame()])
    normalizer = FakeNormalizer((processing_frame,))
    vad = FakeVad()
    assembler = FakeAssembler(
        {
            id(processing_frame): (
                segment_one,
                segment_two,
            ),
        }
    )
    transcription_executor = FakeTranscriptionExecutor()

    pipeline = SpeechPipeline(
        capture=capture,
        normalizer=normalizer,
        vad=vad,
        assembler=assembler,
        transcription_executor=transcription_executor,
    )

    await pipeline.start()
    await pipeline.wait()

    assert transcription_executor.submitted == [
        segment_one,
        segment_two,
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
        capture=capture,
        normalizer=normalizer,
        vad=vad,
        assembler=assembler,
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
        capture=capture,
        normalizer=normalizer,
        vad=vad,
        assembler=assembler,
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
        capture=capture,
        normalizer=normalizer,
        vad=vad,
        assembler=assembler,
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
        capture=capture,
        normalizer=normalizer,
        vad=vad,
        assembler=assembler,
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
        capture=capture,
        normalizer=normalizer,
        vad=vad,
        assembler=assembler,
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
        capture=capture,
        normalizer=normalizer,
        vad=vad,
        assembler=assembler,
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
        capture=capture,
        normalizer=normalizer,
        vad=vad,
        assembler=assembler,
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

    pipeline = SpeechPipeline(
        capture=capture,
        normalizer=FakeNormalizer((processing_frame,)),
        vad=VadWithEvents(),
        assembler=FakeAssembler({id(processing_frame): (segment,)}),
        transcription_executor=transcription_executor,
    )

    # Act
    with caplog.at_level("INFO", logger="app.services.speech_pipeline"):
        await pipeline.start()
        await pipeline.wait()
        await pipeline.stop()

    # Assert
    messages = [record.getMessage() for record in caplog.records]
    assert any("VAD SpeechStart timestamp=12.000" in message for message in messages)
    assert any("speech segment emitted id=1" in message for message in messages)
    assert any(
        "speech pipeline stopped captured_frames=1 processing_frames=1 "
        "segments_emitted=1 segments_rejected=0" in message
        for message in messages
    )


@pytest.mark.anyio
async def test_pipeline_continues_when_transcription_executor_rejects_segment() -> None:
    processing_frame = create_processing_frame()
    segment = create_speech_segment()

    transcription_executor = FakeTranscriptionExecutor()
    transcription_executor.accept = False

    pipeline = SpeechPipeline(
        capture=FakeAudioCapture([create_audio_frame()]),
        normalizer=FakeNormalizer((processing_frame,)),
        vad=FakeVad(),
        assembler=FakeAssembler(
            {id(processing_frame): (segment,)},
        ),
        transcription_executor=transcription_executor,
    )

    await pipeline.start()
    await pipeline.wait()

    assert transcription_executor.attempted == [segment]
    assert transcription_executor.submitted == []


@pytest.mark.anyio
async def test_pipeline_starts_and_stops_transcription_executor() -> None:
    executor = FakeTranscriptionExecutor()

    pipeline = create_pipeline(
        transcription_executor=executor,
    )

    await pipeline.start()

    assert executor.started is True

    await pipeline.stop()

    assert executor.stopped is True
