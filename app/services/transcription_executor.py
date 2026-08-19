from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass
from typing import Protocol

from app.audio.contracts import SpeechSegment
from app.transcription.protocols import Transcriber, TranscriptionResultHandler

logger = logging.getLogger(__name__)


class _Shutdown:
    """Internal transcription-worker shutdown signal."""


class TranscriptionExecutor(Protocol):
    """Execute transcription independently from real-time audio processing."""

    async def start(self) -> None:
        """Start the transcription worker."""

    def submit(self, segment: SpeechSegment) -> bool:
        """Submit a speech segment without blocking the caller."""

    async def stop(self) -> None:
        """Stop the worker after accepted work has been processed."""


@dataclass(slots=True)
class TranscriptionExecutorStats:
    accepted: int = 0
    rejected: int = 0
    completed: int = 0
    failed: int = 0
    max_queue_depth: int = 0


class TranscriptionExecutorImpl:
    """Execute speech-segment transcription on a dedicated worker."""

    _SHUTDOWN = _Shutdown()

    def __init__(
        self,
        transcriber: Transcriber,
        on_result: TranscriptionResultHandler,
        queue_capacity: int,
    ) -> None:
        if queue_capacity < 1:
            raise ValueError("queue_capacity must be at least 1")

        self._transcriber = transcriber
        self._on_result = on_result
        self._queue: asyncio.Queue[SpeechSegment | _Shutdown] = asyncio.Queue(
            maxsize=queue_capacity,
        )
        self._worker_task: asyncio.Task[None] | None = None
        self._started = False
        self._accepting = False
        self._stats = TranscriptionExecutorStats()

    @property
    def stats(self) -> TranscriptionExecutorStats:
        return TranscriptionExecutorStats(
            accepted=self._stats.accepted,
            rejected=self._stats.rejected,
            completed=self._stats.completed,
            failed=self._stats.failed,
            max_queue_depth=self._stats.max_queue_depth,
        )

    async def start(self) -> None:
        """Start accepting segments and launch the worker."""

        if self._started:
            return

        self._started = True
        self._accepting = True

        self._worker_task = asyncio.create_task(
            self._run(),
            name="transcription-executor",
        )

        logger.info(
            "transcription executor started queue_capacity=%d",
            self._queue.maxsize,
        )

    def submit(self, segment: SpeechSegment) -> bool:
        """Submit a segment without blocking the real-time pipeline."""

        if not self._accepting:
            return False

        try:
            self._queue.put_nowait(segment)
        except asyncio.QueueFull:
            self._stats.rejected += 1

            logger.warning(
                "transcription executor overloaded queue_capacity=%d rejected=%d",
                self._queue.maxsize,
                self._stats.rejected,
            )
            return False

        self._stats.accepted += 1

        queue_depth = self._queue.qsize()
        self._stats.max_queue_depth = max(
            self._stats.max_queue_depth,
            queue_depth,
        )

        return True

    async def stop(self) -> None:
        """Stop accepting work and drain accepted segments."""

        if not self._started:
            return

        self._accepting = False

        worker_task = self._worker_task
        if worker_task is None:
            self._started = False
            return

        # Wait until every accepted segment has been processed.
        await self._queue.join()

        # The queue is now empty, so the sentinel can safely terminate
        # the worker without discarding accepted work.
        await self._queue.put(self._SHUTDOWN)

        with contextlib.suppress(asyncio.CancelledError):
            await worker_task

        self._worker_task = None
        self._started = False

        logger.info("transcription executor stopped")

    async def _run(self) -> None:
        while True:
            item = await self._queue.get()

            try:
                if isinstance(item, _Shutdown):
                    return

                result = await asyncio.to_thread(
                    self._transcriber.transcribe,
                    item,
                )

                self._stats.completed += 1

                logger.info(
                    "transcription completed start=%.3f end=%.3f",
                    result.start,
                    result.end,
                )
                logger.debug(
                    "transcription result language=%s text=%r",
                    result.language,
                    result.text,
                )

                self._on_result(result)

            except Exception:
                if isinstance(item, _Shutdown):
                    raise

                self._stats.failed += 1

                logger.exception(
                    "transcription execution failed start=%.3f end=%.3f",
                    item.timestamp,
                    item.timestamp + item.duration,
                )

            finally:
                self._queue.task_done()
