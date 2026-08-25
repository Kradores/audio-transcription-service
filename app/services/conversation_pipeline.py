from __future__ import annotations

import asyncio
import logging

from app.services.speech_pipeline import SpeechPipeline
from app.services.transcription_executor import TranscriptionExecutor

logger = logging.getLogger(__name__)


class ConversationPipeline:
    """Coordinate source pipelines around shared transcription execution."""

    def __init__(
        self,
        *,
        transcription_executor: TranscriptionExecutor,
        system_pipeline: SpeechPipeline,
        microphone_pipeline: SpeechPipeline,
    ) -> None:
        self._transcription_executor = transcription_executor
        self._system_pipeline = system_pipeline
        self._microphone_pipeline = microphone_pipeline
        self._started = False

    async def start(self) -> None:
        """Start shared transcription and both source pipelines."""
        if self._started:
            raise RuntimeError("conversation pipeline has already been started")

        await self._transcription_executor.start()

        system_started = False

        try:
            await self._system_pipeline.start()
            system_started = True

            await self._microphone_pipeline.start()

        except Exception:
            logger.exception("conversation pipeline startup failed")

            if system_started:
                try:
                    await self._system_pipeline.stop()
                except Exception:
                    logger.exception(
                        "failed to stop system pipeline during startup rollback",
                    )

            try:
                await self._transcription_executor.stop()
            except Exception:
                logger.exception(
                    "failed to stop transcription executor during startup rollback",
                )

            raise

        self._started = True
        logger.info("conversation pipeline started")

    async def stop(self) -> None:
        """Stop both source pipelines before draining transcription."""
        if not self._started:
            return

        self._started = False

        errors: list[Exception] = []

        try:
            await self._system_pipeline.stop()
        except Exception as exc:
            logger.exception("failed to stop system pipeline")
            errors.append(exc)

        try:
            await self._microphone_pipeline.stop()
        except Exception as exc:
            logger.exception("failed to stop microphone pipeline")
            errors.append(exc)

        try:
            await self._transcription_executor.stop()
        except Exception as exc:
            logger.exception("failed to stop transcription executor")
            errors.append(exc)

        logger.info("conversation pipeline stopped")

        if errors:
            raise ExceptionGroup(
                "conversation pipeline shutdown failed",
                errors,
            )

    async def wait(self) -> None:
        """Wait for an unexpected source-pipeline termination."""

        system_wait = asyncio.create_task(
            self._system_pipeline.wait(),
            name="system-speech-pipeline-wait",
        )
        microphone_wait = asyncio.create_task(
            self._microphone_pipeline.wait(),
            name="microphone-speech-pipeline-wait",
        )

        executor_wait = asyncio.create_task(
            self._transcription_executor.wait(),
            name="transcription-executor-wait",
        )

        waiters = {
            system_wait: "system_audio",
            microphone_wait: "microphone",
            executor_wait: "transcription_executor",
        }

        try:
            done, _ = await asyncio.wait(
                waiters,
                return_when=asyncio.FIRST_COMPLETED,
            )

            completed = next(iter(done))
            source = waiters[completed]

            try:
                await completed
            except Exception:
                logger.exception(
                    "conversation component failed component=%s",
                    source,
                )
                raise

            raise RuntimeError(
                f"conversation component stopped unexpectedly: {source}",
            )

        finally:
            for waiter in waiters:
                if not waiter.done():
                    waiter.cancel()

            await asyncio.gather(
                *waiters,
                return_exceptions=True,
            )
