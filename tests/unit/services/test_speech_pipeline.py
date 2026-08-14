from __future__ import annotations

import asyncio
import threading
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
from app.transcription.contracts import TranscriptionResult
from app.transcription.protocols import Transcriber
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

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True

    async def frames(self) -> AsyncIterator[AudioFrame]:
        for frame in self._frames:
            yield frame


class FakeNormalizer:
    def __init__(
        self,
        processing_frames: tuple[ProcessingAudioFrame, ...],
        flushed_frames: tuple[ProcessingAudioFrame, ...] = (),
    ) -> None:
        self.processing_frames = processing_frames
        self.flushed_frames = flushed_frames

        self.processed: list[AudioFrame] = []
        self.flush_called = False

    def process(
        self,
        frame: AudioFrame,
    ) -> tuple[ProcessingAudioFrame, ...]:
        self.processed.append(frame)
        return self.processing_frames

    def flush(self) -> tuple[ProcessingAudioFrame, ...]:
        self.flush_called = True
        return self.flushed_frames


class FakeVad:
    def __init__(self) -> None:
        self.processed: list[ProcessingAudioFrame] = []
        self.reset_called = False

    def process(self, frame: ProcessingAudioFrame) -> tuple[SpeechStart | SpeechEnd, ...]:
        self.processed.append(frame)
        return ()

    def reset(self) -> None:
        self.reset_called = True


class FakeAssembler:
    def __init__(
        self,
        segments_by_frame: dict[int, tuple[SpeechSegment, ...]],
    ) -> None:
        self._segments_by_frame = segments_by_frame
        self.processed: list[ProcessingAudioFrame] = []
        self.reset_called = False

    def process(
        self,
        frame: ProcessingAudioFrame,
        events: tuple[SpeechStart | SpeechEnd, ...],
    ) -> tuple[SpeechSegment, ...]:
        self.processed.append(frame)
        return self._segments_by_frame.get(id(frame), ())

    def reset(self) -> None:
        self.reset_called = True

    def flush(self) -> tuple[SpeechSegment, ...]:
        return ()


class FakeTranscriber:
    def __init__(self) -> None:
        self.transcribed: list[object] = []

    def transcribe(self, segment: object) -> TranscriptionResult:
        self.transcribed.append(segment)

        return TranscriptionResult(
            text=f"text-{len(self.transcribed)}",
            language="en",
            confidence=None,
            start=0.0,
            end=1.0,
        )


class BlockingTranscriber:
    def __init__(self) -> None:
        self.started: list[object] = []
        self.completed: list[object] = []

        self.first_started = threading.Event()
        self.allow_first_to_finish = threading.Event()

    def transcribe(self, segment: object) -> TranscriptionResult:
        self.started.append(segment)

        if len(self.started) == 1:
            self.first_started.set()
            self.allow_first_to_finish.wait()

        self.completed.append(segment)

        return TranscriptionResult(
            text="text",
            language="en",
            confidence=None,
            start=0.0,
            end=1.0,
        )


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
    transcriber: Transcriber | None = None,
    on_result: Callable[[TranscriptionResult], None] | None = None,
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

    if transcriber is None:
        transcriber = FakeTranscriber()

    def does_nothing(_: TranscriptionResult) -> None:
        """Does nothing"""

    if on_result is None:
        on_result = does_nothing

    return SpeechPipeline(
        capture=capture,
        normalizer=normalizer,
        vad=vad,
        assembler=assembler,
        transcriber=transcriber,
        on_result=on_result,
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
    transcriber = FakeTranscriber()

    results: list[TranscriptionResult] = []

    pipeline = SpeechPipeline(
        capture=capture,
        normalizer=normalizer,
        vad=vad,
        assembler=assembler,
        transcriber=transcriber,
        on_result=results.append,
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
    assert transcriber.transcribed == [segment]
    assert len(results) == 1
    assert results[0].text == "text-1"


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
    transcriber = FakeTranscriber()

    pipeline = SpeechPipeline(
        capture=capture,
        normalizer=normalizer,
        vad=vad,
        assembler=assembler,
        transcriber=transcriber,
        on_result=lambda _: None,
    )

    await pipeline.start()
    await asyncio.sleep(0)
    await pipeline.stop()

    assert vad.processed == list(processing_frames)
    assert assembler.processed == list(processing_frames)


@pytest.mark.anyio
async def test_pipeline_transcribes_all_segments_from_one_processing_frame() -> None:
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
    transcriber = FakeTranscriber()

    results: list[TranscriptionResult] = []

    pipeline = SpeechPipeline(
        capture=capture,
        normalizer=normalizer,
        vad=vad,
        assembler=assembler,
        transcriber=transcriber,
        on_result=results.append,
    )

    await pipeline.start()
    await pipeline.wait()

    assert len(transcriber.transcribed) == 2
    assert transcriber.transcribed[0] is segment_one
    assert transcriber.transcribed[1] is segment_two
    assert len(results) == 2


@pytest.mark.anyio
async def test_pipeline_transcribes_segments_sequentially() -> None:
    processing_frame = create_processing_frame()

    segment_one = create_speech_segment()
    segment_two = create_speech_segment()

    transcriber = BlockingTranscriber()

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

    pipeline = SpeechPipeline(
        capture=capture,
        normalizer=normalizer,
        vad=vad,
        assembler=assembler,
        transcriber=transcriber,
        on_result=lambda _: None,
    )

    await pipeline.start()

    await asyncio.to_thread(
        transcriber.first_started.wait,
    )

    assert len(transcriber.started) == 1
    assert transcriber.started[0] is segment_one
    assert transcriber.completed == []

    transcriber.allow_first_to_finish.set()

    await pipeline.wait()

    assert len(transcriber.started) == 2
    assert transcriber.started[0] is segment_one
    assert transcriber.started[1] is segment_two

    assert len(transcriber.completed) == 2
    assert transcriber.completed[0] is segment_one
    assert transcriber.completed[1] is segment_two


@pytest.mark.anyio
async def test_pipeline_runs_transcription_without_blocking_event_loop() -> None:
    processing_frame = create_processing_frame()
    segment = create_speech_segment()

    started = threading.Event()
    release = threading.Event()

    class BlockingTranscriber:
        def transcribe(
            self,
            segment: object,
        ) -> TranscriptionResult:
            started.set()
            release.wait()

            return TranscriptionResult(
                text="text",
                language="en",
                confidence=None,
                start=0.0,
                end=1.0,
            )

    transcriber = BlockingTranscriber()

    pipeline = SpeechPipeline(
        capture=FakeAudioCapture([create_audio_frame()]),
        normalizer=FakeNormalizer((processing_frame,)),
        vad=FakeVad(),
        assembler=FakeAssembler({id(processing_frame): (segment,)}),
        transcriber=transcriber,
        on_result=lambda _: None,
    )

    await pipeline.start()

    await asyncio.to_thread(started.wait)

    # The event loop must still be able to run.
    await asyncio.sleep(0)

    release.set()

    await pipeline.stop()


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
    transcriber = FakeTranscriber()

    pipeline = SpeechPipeline(
        capture=capture,
        normalizer=normalizer,
        vad=vad,
        assembler=assembler,
        transcriber=transcriber,
        on_result=lambda _: None,
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
async def test_pipeline_propagates_transcriber_failure() -> None:
    class FailingTranscriber:
        def transcribe(
            self,
            segment: SpeechSegment,
        ) -> TranscriptionResult:
            raise RuntimeError("transcription failed")

    pipeline = create_pipeline(
        transcriber=FailingTranscriber(),
        segments=(create_speech_segment(),),
    )

    await pipeline.start()

    with pytest.raises(
        RuntimeError,
        match="transcription failed",
    ):
        await pipeline.wait()


@pytest.mark.anyio
async def test_stop_discards_incomplete_assembler_state() -> None:
    assembler = FakeAssembler({})

    pipeline = create_pipeline(
        assembler=assembler,
    )

    await pipeline.start()
    await pipeline.stop()

    assert assembler.reset_called


@pytest.mark.anyio
async def test_wait_before_start_is_harmless() -> None:
    pipeline = create_pipeline()

    await pipeline.wait()
