from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from dataclasses import dataclass
from typing import Protocol

from app.transcription.contracts import (
    SourcedTranscriptionResult,
    TranscriptionWorkItem,
)
from app.transcription.protocols import (
    SourcedTranscriptionResultHandler,
    Transcriber,
)

logger = logging.getLogger(__name__)


class _Shutdown:
    """Internal transcription-worker shutdown signal."""


@dataclass(frozen=True, slots=True)
class _QueuedWorkItem:
    """Executor-local wrapper used to measure queue wait time."""

    item: TranscriptionWorkItem
    enqueued_at: float


@dataclass(frozen=True, slots=True)
class TranscriptionExecutorStats:
    submitted: int
    completed: int
    rejected: int
    failed: int

    queue_depth: int
    queue_high_water_mark: int

    queue_wait_seconds_total: float
    queue_wait_seconds_max: float
    queue_wait_samples: int

    transcription_seconds_total: float
    transcription_seconds_max: float

    @property
    def queue_wait_seconds_average(self) -> float:
        if self.queue_wait_samples == 0:
            return 0.0

        return self.queue_wait_seconds_total / self.queue_wait_samples

    @property
    def transcription_seconds_average(self) -> float:
        processed = self.completed + self.failed

        if processed == 0:
            return 0.0

        return self.transcription_seconds_total / processed


class TranscriptionExecutor(Protocol):
    """Execute transcription independently from real-time audio processing."""

    async def start(self) -> None:
        """Start the transcription worker."""

    def submit(self, item: TranscriptionWorkItem) -> bool:
        """Submit a speech segment without blocking the caller."""

    async def stop(self) -> None:
        """Stop the worker after accepted work has been processed."""


class TranscriptionExecutorImpl:
    """Execute speech-segment transcription on a dedicated worker."""

    _SHUTDOWN = _Shutdown()

    def __init__(
        self,
        transcriber: Transcriber,
        on_result: SourcedTranscriptionResultHandler,
        queue_capacity: int,
    ) -> None:
        if queue_capacity < 1:
            raise ValueError("queue_capacity must be at least 1")

        self._transcriber = transcriber
        self._on_result = on_result

        self._queue: asyncio.Queue[_QueuedWorkItem | _Shutdown] = asyncio.Queue(
            maxsize=queue_capacity,
        )

        self._worker_task: asyncio.Task[None] | None = None

        self._started = False
        self._accepting = False

        self._submitted = 0
        self._completed = 0
        self._rejected = 0
        self._failed = 0

        self._queue_high_water_mark = 0

        self._queue_wait_seconds_total = 0.0
        self._queue_wait_seconds_max = 0.0
        self._queue_wait_samples = 0

        self._transcription_seconds_total = 0.0
        self._transcription_seconds_max = 0.0

    @property
    def stats(self) -> TranscriptionExecutorStats:
        return TranscriptionExecutorStats(
            submitted=self._submitted,
            completed=self._completed,
            rejected=self._rejected,
            failed=self._failed,
            queue_depth=self._queue.qsize(),
            queue_high_water_mark=self._queue_high_water_mark,
            queue_wait_seconds_total=self._queue_wait_seconds_total,
            queue_wait_seconds_max=self._queue_wait_seconds_max,
            queue_wait_samples=self._queue_wait_samples,
            transcription_seconds_total=self._transcription_seconds_total,
            transcription_seconds_max=self._transcription_seconds_max,
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

    def submit(self, item: TranscriptionWorkItem) -> bool:
        """Submit a transcription work item without blocking the real-time pipeline."""

        if not self._accepting:
            return False

        queued_item = _QueuedWorkItem(
            item=item,
            enqueued_at=time.perf_counter(),
        )

        try:
            self._queue.put_nowait(queued_item)

        except asyncio.QueueFull:
            self._rejected += 1

            logger.warning(
                "transcription executor overloaded "
                "source=%s queue_capacity=%d queue_depth=%d "
                "queue_high_water_mark=%d rejected=%d",
                item.source.value,
                self._queue.maxsize,
                self._queue.qsize(),
                self._queue_high_water_mark,
                self._rejected,
            )

            return False

        self._submitted += 1

        queue_depth = self._queue.qsize()

        self._queue_high_water_mark = max(
            self._queue_high_water_mark,
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

        # Drain all work accepted before shutdown.
        await self._queue.join()

        # The queue is now empty, so the sentinel can terminate the worker
        # without discarding accepted work.
        await self._queue.put(self._SHUTDOWN)

        with contextlib.suppress(asyncio.CancelledError):
            await worker_task

        self._worker_task = None
        self._started = False

        stats = self.stats

        logger.info(
            "transcription executor stopped "
            "submitted=%d completed=%d rejected=%d failed=%d "
            "queue_high_water_mark=%d "
            "avg_queue_wait=%.3f max_queue_wait=%.3f "
            "avg_transcription_duration=%.3f "
            "max_transcription_duration=%.3f",
            stats.submitted,
            stats.completed,
            stats.rejected,
            stats.failed,
            stats.queue_high_water_mark,
            stats.queue_wait_seconds_average,
            stats.queue_wait_seconds_max,
            stats.transcription_seconds_average,
            stats.transcription_seconds_max,
        )

    async def _run(self) -> None:
        while True:
            queued_item = await self._queue.get()

            try:
                if isinstance(queued_item, _Shutdown):
                    return

                item = queued_item.item

                transcription_started_at = time.perf_counter()

                queue_wait_seconds = transcription_started_at - queued_item.enqueued_at

                self._queue_wait_seconds_total += queue_wait_seconds
                self._queue_wait_seconds_max = max(
                    self._queue_wait_seconds_max,
                    queue_wait_seconds,
                )
                self._queue_wait_samples += 1

                try:
                    result = await asyncio.to_thread(
                        self._transcriber.transcribe,
                        item.segment,
                    )
                finally:
                    transcription_seconds = time.perf_counter() - transcription_started_at

                    self._transcription_seconds_total += transcription_seconds
                    self._transcription_seconds_max = max(
                        self._transcription_seconds_max,
                        transcription_seconds,
                    )

                logger.info(
                    "transcription completed source=%s start=%.3f end=%.3f",
                    item.source.value,
                    result.start,
                    result.end,
                )

                logger.debug(
                    "transcription result source=%s language=%s text=%r",
                    item.source.value,
                    result.language,
                    result.text,
                )

                self._on_result(
                    SourcedTranscriptionResult(
                        source=item.source,
                        result=result,
                    )
                )

                self._completed += 1

            except Exception:
                if isinstance(queued_item, _Shutdown):
                    raise

                self._failed += 1

                item = queued_item.item

                logger.exception(
                    "transcription execution failed source=%s start=%.3f end=%.3f",
                    item.source.value,
                    item.segment.timestamp,
                    item.segment.timestamp + item.segment.duration,
                )

            finally:
                self._queue.task_done()
