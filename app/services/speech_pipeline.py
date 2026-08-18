from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass

from app.audio.contracts import ProcessingAudioFrame
from app.audio.protocols import AudioCapture, AudioNormalizer
from app.services.transcription_executor import TranscriptionExecutor
from app.vad.protocols import AudioVad, SpeechSegmentAssembler

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class _SpeechPipelineStats:
    """Runtime counters used to diagnose processing-boundary losses."""

    captured_frames: int = 0
    processing_frames: int = 0
    segments_emitted: int = 0
    segments_rejected: int = 0


class SpeechPipeline:
    """Orchestrate audio processing from capture through transcription."""

    def __init__(
        self,
        capture: AudioCapture,
        normalizer: AudioNormalizer,
        vad: AudioVad,
        assembler: SpeechSegmentAssembler,
        transcription_executor: TranscriptionExecutor,
    ) -> None:
        self._capture = capture
        self._normalizer = normalizer
        self._vad = vad
        self._assembler = assembler
        self._transcription_executor = transcription_executor

        self._task: asyncio.Task[None] | None = None
        self._started = False

        self._discontinuity_pending = False
        self._next_segment_id = 1
        self._stats = _SpeechPipelineStats()

        self._capture.set_discontinuity_handler(
            self._handle_capture_discontinuity,
        )

    async def start(self) -> None:
        """Start transcription execution, capture, and pipeline processing."""
        if self._started:
            raise RuntimeError("pipeline has already been started")

        await self._transcription_executor.start()
        await self._capture.start()

        self._stats = _SpeechPipelineStats()
        self._next_segment_id = 1
        self._started = True

        logger.info("speech pipeline started")

        self._task = asyncio.create_task(
            self._run(),
            name="speech-pipeline",
        )

    async def stop(self) -> None:
        """Stop the pipeline and drain accepted transcription work."""
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

        await self._transcription_executor.stop()

        logger.info(
            "speech pipeline stopped captured_frames=%d processing_frames=%d "
            "segments_emitted=%d segments_rejected=%d",
            self._stats.captured_frames,
            self._stats.processing_frames,
            self._stats.segments_emitted,
            self._stats.segments_rejected,
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
                self._stats.captured_frames += 1

                if self._discontinuity_pending:
                    self._reset_processing_state()

                processing_frames = self._normalizer.process(frame)

                self._stats.processing_frames += len(processing_frames)

                for processing_frame in processing_frames:
                    await self._process_frame(processing_frame)

            flushed_frames = self._normalizer.flush()
            self._stats.processing_frames += len(flushed_frames)

            for processing_frame in flushed_frames:
                await self._process_frame(processing_frame)

        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Speech pipeline processing failed")
            await self._capture.stop()
            raise

    async def _process_frame(self, frame: ProcessingAudioFrame) -> None:
        events = self._vad.process(frame)

        for event in events:
            logger.info(
                "VAD %s timestamp=%.3f",
                type(event).__name__,
                event.timestamp,
            )

        segments = self._assembler.process(
            frame,
            events,
        )

        for segment in segments:
            segment_id = self._next_segment_id
            self._next_segment_id += 1
            self._stats.segments_emitted += 1

            logger.info(
                "speech segment emitted id=%d start=%.3f duration=%.3f end=%.3f",
                segment_id,
                segment.timestamp,
                segment.duration,
                segment.timestamp + segment.duration,
            )

            accepted = self._transcription_executor.submit(segment)

            if not accepted:
                self._stats.segments_rejected += 1

                logger.warning(
                    "speech segment rejected by transcription executor id=%d start=%.3f end=%.3f",
                    segment_id,
                    segment.timestamp,
                    segment.timestamp + segment.duration,
                )

    def _handle_capture_discontinuity(self) -> None:
        """Mark capture discontinuity for processing by the pipeline task."""
        self._discontinuity_pending = True

    def _reset_processing_state(self) -> None:
        logger.warning("capture discontinuity detected; resetting processing state")
        self._normalizer.reset()
        self._vad.reset()
        self._assembler.reset()
        self._discontinuity_pending = False
