from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Sequence
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

    worker_count: int
    active_workers: int
    active_workers_high_water_mark: int

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
        """Start transcription workers."""

    def submit(self, item: TranscriptionWorkItem) -> bool:
        """Submit a speech segment without blocking the caller."""

    async def stop(self) -> None:
        """Stop workers after accepted work has been processed."""

    async def wait(self) -> None:
        """Wait until an executor worker terminates unexpectedly."""


class TranscriptionExecutorImpl:
    """Execute speech-segment transcription on a dedicated worker."""

    _SHUTDOWN = _Shutdown()

    def __init__(
        self,
        transcribers: Sequence[Transcriber],
        on_result: SourcedTranscriptionResultHandler,
        queue_capacity: int,
    ) -> None:
        if queue_capacity < 1:
            raise ValueError("queue_capacity must be at least 1")

        if not transcribers:
            raise ValueError("at least one transcriber is required")

        self._transcribers = tuple(transcribers)
        self._on_result = on_result

        self._queue: asyncio.Queue[_QueuedWorkItem | _Shutdown] = asyncio.Queue(
            maxsize=queue_capacity,
        )

        self._worker_tasks: tuple[asyncio.Task[None], ...] = ()
        self._worker_failure: asyncio.Future[BaseException] | None = None
        self._stopping = False

        self._started = False
        self._accepting = False

        self._submitted = 0
        self._completed = 0
        self._rejected = 0
        self._failed = 0

        self._active_workers = 0
        self._active_workers_high_water_mark = 0

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
            worker_count=len(self._transcribers),
            active_workers=self._active_workers,
            active_workers_high_water_mark=self._active_workers_high_water_mark,
            queue_wait_seconds_total=self._queue_wait_seconds_total,
            queue_wait_seconds_max=self._queue_wait_seconds_max,
            queue_wait_samples=self._queue_wait_samples,
            transcription_seconds_total=self._transcription_seconds_total,
            transcription_seconds_max=self._transcription_seconds_max,
        )

    async def start(self) -> None:
        """Start accepting segments and launch transcription workers."""

        if self._started:
            return

        self._started = True
        self._accepting = True
        self._stopping = False

        self._worker_failure = asyncio.get_running_loop().create_future()

        worker_tasks = tuple(
            asyncio.create_task(
                self._run(
                    worker_id=worker_id,
                    transcriber=transcriber,
                ),
                name=f"transcription-executor-worker-{worker_id}",
            )
            for worker_id, transcriber in enumerate(
                self._transcribers,
                start=1,
            )
        )

        for worker_task in worker_tasks:
            worker_task.add_done_callback(self._on_worker_done)

        self._worker_tasks = worker_tasks

        logger.info(
            "transcription executor started queue_capacity=%d worker_count=%d",
            self._queue.maxsize,
            len(self._transcribers),
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
        """Stop accepting work and drain accepted transcription."""

        if not self._started:
            return

        self._accepting = False
        self._stopping = True

        worker_tasks = self._worker_tasks
        lifecycle_failure: BaseException | None = None

        worker_failure = self._worker_failure

        if worker_failure is not None and worker_failure.done() and not worker_failure.cancelled():
            lifecycle_failure = worker_failure.result()

        try:
            await self._drain_accepted_work(worker_tasks)

            live_workers = tuple(
                worker_task for worker_task in worker_tasks if not worker_task.done()
            )

            for _ in live_workers:
                await self._queue.put(self._SHUTDOWN)

            await asyncio.gather(
                *worker_tasks,
                return_exceptions=True,
            )

        finally:
            self._worker_tasks = ()
            self._worker_failure = None
            self._started = False
            self._stopping = False

        stats = self.stats

        logger.info(
            "transcription executor stopped "
            "worker_count=%d "
            "max_active_workers=%d "
            "submitted=%d completed=%d rejected=%d failed=%d "
            "queue_high_water_mark=%d "
            "avg_queue_wait=%.3f max_queue_wait=%.3f "
            "avg_transcription_duration=%.3f "
            "max_transcription_duration=%.3f",
            stats.worker_count,
            stats.active_workers_high_water_mark,
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

        if lifecycle_failure is not None:
            raise RuntimeError(
                "transcription executor worker terminated unexpectedly"
            ) from lifecycle_failure

    async def wait(self) -> None:
        """Wait for unexpected transcription-worker termination."""

        worker_failure = self._worker_failure

        if not self._started or worker_failure is None:
            raise RuntimeError("transcription executor is not running")

        failure = await asyncio.shield(worker_failure)

        raise RuntimeError("transcription executor worker terminated unexpectedly") from failure

    async def _run(
        self,
        *,
        worker_id: int,
        transcriber: Transcriber,
    ) -> None:
        logger.info(
            "transcription worker started worker_id=%d",
            worker_id,
        )

        try:
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

                    self._active_workers += 1
                    self._active_workers_high_water_mark = max(
                        self._active_workers_high_water_mark,
                        self._active_workers,
                    )

                    try:
                        result = await asyncio.to_thread(
                            transcriber.transcribe,
                            item.segment,
                        )
                    finally:
                        self._active_workers -= 1

                        transcription_seconds = time.perf_counter() - transcription_started_at

                        self._transcription_seconds_total += transcription_seconds
                        self._transcription_seconds_max = max(
                            self._transcription_seconds_max,
                            transcription_seconds,
                        )

                    logger.info(
                        "transcription completed worker_id=%d source=%s "
                        "start=%.3f end=%.3f duration=%.3f "
                        "language=%s confidence=%s",
                        worker_id,
                        item.source.value,
                        result.start,
                        result.end,
                        result.end - result.start,
                        result.language,
                        (f"{result.confidence:.3f}" if result.confidence is not None else "none"),
                    )

                    logger.debug(
                        "transcription result worker_id=%d source=%s "
                        "language=%s confidence=%s text=%r",
                        worker_id,
                        item.source.value,
                        result.language,
                        result.confidence,
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
                        "transcription execution failed worker_id=%d source=%s start=%.3f end=%.3f",
                        worker_id,
                        item.source.value,
                        item.segment.timestamp,
                        item.segment.timestamp + item.segment.duration,
                    )

                finally:
                    self._queue.task_done()
        finally:
            logger.info(
                "transcription worker stopped worker_id=%d",
                worker_id,
            )

    def _on_worker_done(
        self,
        worker_task: asyncio.Task[None],
    ) -> None:
        if self._stopping:
            return

        if worker_task.cancelled():
            failure: BaseException = RuntimeError(
                f"transcription worker cancelled unexpectedly: {worker_task.get_name()}"
            )
        else:
            exception = worker_task.exception()

            if exception is None:
                failure = RuntimeError(
                    f"transcription worker stopped unexpectedly: {worker_task.get_name()}"
                )
            else:
                failure = exception

        self._accepting = False

        logger.error(
            "transcription worker terminated unexpectedly worker=%s failure=%r",
            worker_task.get_name(),
            failure,
        )

        worker_failure = self._worker_failure

        if worker_failure is not None and not worker_failure.done():
            worker_failure.set_result(failure)

    async def _drain_accepted_work(
        self,
        worker_tasks: tuple[asyncio.Task[None], ...],
    ) -> None:
        join_task = asyncio.create_task(
            self._queue.join(),
            name="transcription-executor-drain",
        )

        live_workers = set(worker_tasks)

        try:
            while not join_task.done():
                if not live_workers:
                    raise RuntimeError(
                        "all transcription workers stopped before accepted work was drained"
                    )

                done, _ = await asyncio.wait(
                    {join_task, *live_workers},
                    return_when=asyncio.FIRST_COMPLETED,
                )

                if join_task in done:
                    break

                live_workers.difference_update(done)

            await join_task

        finally:
            if not join_task.done():
                join_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await join_task
