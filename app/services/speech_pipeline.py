from __future__ import annotations

import asyncio
import contextlib
import logging

from app.audio.contracts import ProcessingAudioFrame
from app.audio.protocols import AudioCapture, AudioNormalizer
from app.transcription.protocols import Transcriber, TranscriptionResultHandler
from app.vad.protocols import AudioVad, SpeechSegmentAssembler

logger = logging.getLogger(__name__)


class SpeechPipeline:
    """Orchestrate audio processing from capture through transcription."""

    def __init__(
        self,
        capture: AudioCapture,
        normalizer: AudioNormalizer,
        vad: AudioVad,
        assembler: SpeechSegmentAssembler,
        transcriber: Transcriber,
        on_result: TranscriptionResultHandler,
    ) -> None:
        self._capture = capture
        self._normalizer = normalizer
        self._vad = vad
        self._assembler = assembler
        self._transcriber = transcriber
        self._on_result = on_result

        self._task: asyncio.Task[None] | None = None
        self._started = False

    async def start(self) -> None:
        """Start capture and the pipeline processing task."""
        if self._started:
            raise RuntimeError("pipeline has already been started")

        await self._capture.start()

        self._started = True
        self._task = asyncio.create_task(
            self._run(),
            name="speech-pipeline",
        )

    async def stop(self) -> None:
        """Stop the pipeline and discard incomplete segmentation state."""
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

        self._assembler.reset()
        self._vad.reset()

    async def _run(self) -> None:
        try:
            async for frame in self._capture.frames():
                processing_frames = self._normalizer.process(frame)

                for processing_frame in processing_frames:
                    await self._process_frame(processing_frame)

            for processing_frame in self._normalizer.flush():
                await self._process_frame(processing_frame)

        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Speech pipeline processing failed")
            await self._capture.stop()
            raise

    async def wait(self) -> None:
        """Wait for the pipeline processing task to complete."""

        task = self._task

        if task is None:
            return

        await task

    async def _process_frame(self, frame: ProcessingAudioFrame) -> None:
        events = self._vad.process(frame)

        segments = self._assembler.process(
            frame,
            events,
        )

        for segment in segments:
            result = await asyncio.to_thread(
                self._transcriber.transcribe,
                segment,
            )

            self._on_result(result)
