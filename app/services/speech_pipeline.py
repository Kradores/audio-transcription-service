from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass

from app.audio.contracts import ProcessingAudioFrame, SpeechSegment
from app.audio.protocols import AudioCapture, AudioNormalizer
from app.services.transcription_executor import TranscriptionExecutor
from app.transcription.contracts import AudioSource, TranscriptionWorkItem
from app.transcription.protocols import TranscriptionSegmentAggregator
from app.vad.protocols import AudioVad, SpeechSegmentAssembler

logger = logging.getLogger(__name__)

SHORT_SEGMENT_THRESHOLD_SECONDS = 1.0


@dataclass(frozen=True, slots=True)
class SpeechPipelineStats:
    captured_frames: int
    processing_frames: int
    segments_emitted: int
    segments_rejected: int

    segment_seconds_total: float
    segment_seconds_max: float
    short_segments: int

    @property
    def segment_seconds_average(self) -> float:
        if self.segments_emitted == 0:
            return 0.0

        return self.segment_seconds_total / self.segments_emitted


class SpeechPipeline:
    """Orchestrate audio processing from capture through transcription."""

    def __init__(
        self,
        *,
        source: AudioSource,
        capture: AudioCapture,
        normalizer: AudioNormalizer,
        vad: AudioVad,
        assembler: SpeechSegmentAssembler,
        transcription_segment_aggregator: TranscriptionSegmentAggregator,
        transcription_executor: TranscriptionExecutor,
    ) -> None:
        self._source = source
        self._capture = capture
        self._normalizer = normalizer
        self._vad = vad
        self._assembler = assembler
        self._transcription_segment_aggregator = transcription_segment_aggregator
        self._transcription_executor = transcription_executor

        self._task: asyncio.Task[None] | None = None
        self._started = False

        self._discontinuity_pending = False
        self._next_segment_id = 1

        self._captured_frames = 0
        self._processing_frames = 0
        self._segments_emitted = 0
        self._segments_rejected = 0

        self._segment_seconds_total = 0.0
        self._segment_seconds_max = 0.0
        self._short_segments = 0

        self._capture.set_discontinuity_handler(
            self._handle_capture_discontinuity,
        )

    @property
    def stats(self) -> SpeechPipelineStats:
        return SpeechPipelineStats(
            captured_frames=self._captured_frames,
            processing_frames=self._processing_frames,
            segments_emitted=self._segments_emitted,
            segments_rejected=self._segments_rejected,
            segment_seconds_total=self._segment_seconds_total,
            segment_seconds_max=self._segment_seconds_max,
            short_segments=self._short_segments,
        )

    async def start(self) -> None:
        """Start capture and pipeline processing."""

        if self._started:
            raise RuntimeError("pipeline has already been started")

        await self._capture.start()

        self._captured_frames = 0
        self._processing_frames = 0
        self._segments_emitted = 0
        self._segments_rejected = 0

        self._segment_seconds_total = 0.0
        self._segment_seconds_max = 0.0
        self._short_segments = 0

        self._next_segment_id = 1
        self._started = True

        logger.info(
            "speech pipeline started source=%s",
            self._source.value,
        )

        self._task = asyncio.create_task(
            self._run(),
            name=f"speech-pipeline-{self._source.value}",
        )

    async def stop(self) -> None:
        """Stop capture and pipeline processing."""

        if not self._started:
            return

        await self._capture.stop()

        task = self._task

        self._task = None
        self._started = False

        if task is not None:
            task.cancel()

            with contextlib.suppress(asyncio.CancelledError):
                await task

        stats = self.stats

        logger.info(
            "speech pipeline stopped "
            "source=%s captured_frames=%d processing_frames=%d "
            "segments_emitted=%d segments_rejected=%d "
            "short_segments=%d avg_segment_duration=%.3f "
            "max_segment_duration=%.3f",
            self._source.value,
            stats.captured_frames,
            stats.processing_frames,
            stats.segments_emitted,
            stats.segments_rejected,
            stats.short_segments,
            stats.segment_seconds_average,
            stats.segment_seconds_max,
        )

        self._normalizer.reset()
        self._vad.reset()
        self._assembler.reset()

    async def wait(self) -> None:
        """Wait for the pipeline processing task to complete."""

        task = self._task

        if task is None:
            return

        await task

    async def _run(self) -> None:
        try:
            async for frame in self._capture.frames():
                self._captured_frames += 1

                if self._discontinuity_pending:
                    self._reset_processing_state()

                processing_frames = self._normalizer.process(frame)

                self._processing_frames += len(processing_frames)

                for processing_frame in processing_frames:
                    await self._process_frame(processing_frame)

            flushed_frames = self._normalizer.flush()

            self._processing_frames += len(flushed_frames)

            for processing_frame in flushed_frames:
                await self._process_frame(processing_frame)

        except asyncio.CancelledError:
            raise

        except Exception:
            logger.exception(
                "speech pipeline processing failed source=%s",
                self._source.value,
            )

            await self._capture.stop()

            raise

    async def _process_frame(
        self,
        frame: ProcessingAudioFrame,
    ) -> None:
        for segment in self._transcription_segment_aggregator.advance(frame.timestamp):
            self._submit_transcription_segment(segment)

        events = self._vad.process(frame)

        for event in events:
            logger.info(
                "VAD %s source=%s timestamp=%.3f",
                type(event).__name__,
                self._source.value,
                event.timestamp,
            )

        segments = self._assembler.process(
            frame,
            events,
        )

        for segment in segments:
            segment_id = self._next_segment_id
            self._next_segment_id += 1

            duration = segment.duration

            self._segments_emitted += 1
            self._segment_seconds_total += duration
            self._segment_seconds_max = max(
                self._segment_seconds_max,
                duration,
            )

            if duration < SHORT_SEGMENT_THRESHOLD_SECONDS:
                self._short_segments += 1

            logger.info(
                "speech segment emitted source=%s id=%d start=%.3f duration=%.3f end=%.3f",
                self._source.value,
                segment_id,
                segment.timestamp,
                duration,
                segment.timestamp + duration,
            )

            for transcription_segment in self._transcription_segment_aggregator.process(segment):
                self._submit_transcription_segment(
                    transcription_segment,
                )

    def _handle_capture_discontinuity(self) -> None:
        """Mark capture discontinuity for processing by the pipeline task."""

        self._discontinuity_pending = True

    def _reset_processing_state(self) -> None:
        logger.warning(
            "capture discontinuity detected; resetting processing state source=%s",
            self._source.value,
        )

        self._normalizer.reset()
        self._vad.reset()
        self._assembler.reset()

        self._discontinuity_pending = False

    def _submit_transcription_segment(
        self,
        segment: SpeechSegment,
    ) -> None:
        accepted = self._transcription_executor.submit(
            TranscriptionWorkItem(
                source=self._source,
                segment=segment,
            )
        )

        if accepted:
            return

        self._segments_rejected += 1

        logger.warning(
            "transcription segment rejected by transcription executor "
            "source=%s start=%.3f end=%.3f",
            self._source.value,
            segment.timestamp,
            segment.timestamp + segment.duration,
        )
