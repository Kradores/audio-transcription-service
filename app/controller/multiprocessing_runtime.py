from __future__ import annotations

import asyncio
import contextlib
import multiprocessing
from queue import Empty
from typing import Protocol

from app.controller.runtime_process import (
    RuntimeFailedEvent,
    RuntimeProcessEvent,
    RuntimeProcessSession,
    RuntimeStartedEvent,
)
from app.core.runtime_paths import RuntimePaths

_SHUTDOWN_POLL_INTERVAL_SECONDS = 0.1


class _ShutdownSignal(Protocol):
    def set(self) -> None:
        """Set the process-shared shutdown signal."""

    def is_set(self) -> bool:
        """Return whether shutdown has been requested."""


class _StatusQueue(Protocol):
    def put(
        self,
        item: object,
    ) -> None:
        """Write one status item."""

    def get_nowait(self) -> object:
        """Read one status item without blocking."""

    def close(self) -> None:
        """Close the queue."""

    def join_thread(self) -> None:
        """Wait for the queue feeder thread."""


class _ProcessHandle(Protocol):
    @property
    def pid(self) -> int | None:
        """Return the process ID."""

    @property
    def exitcode(self) -> int | None:
        """Return the process exit code."""

    def start(self) -> None:
        """Start the process."""

    def is_alive(self) -> bool:
        """Return whether the process is alive."""

    def join(
        self,
        timeout: float | None = None,
    ) -> None:
        """Wait for process completion."""

    def close(self) -> None:
        """Release process resources."""


class MultiprocessingRuntimeProcessSession:
    """One runtime process backed by multiprocessing."""

    def __init__(
        self,
        *,
        process: _ProcessHandle,
        shutdown_signal: _ShutdownSignal,
        status_queue: _StatusQueue,
    ) -> None:
        self._process = process
        self._shutdown_signal = shutdown_signal
        self._status_queue = status_queue

    @property
    def pid(self) -> int | None:
        return self._process.pid

    @property
    def exit_code(self) -> int | None:
        return self._process.exitcode

    def start(self) -> None:
        self._process.start()

    def request_stop(self) -> None:
        self._shutdown_signal.set()

    def is_alive(self) -> bool:
        return self._process.is_alive()

    def drain_events(self) -> tuple[RuntimeProcessEvent, ...]:
        events: list[RuntimeProcessEvent] = []

        while True:
            try:
                item = self._status_queue.get_nowait()
            except Empty:
                return tuple(events)

            if isinstance(
                item,
                (RuntimeStartedEvent, RuntimeFailedEvent),
            ):
                events.append(item)

    def wait(
        self,
        timeout_seconds: float | None = None,
    ) -> None:
        self._process.join(timeout_seconds)

    def close(self) -> None:
        self._status_queue.close()
        self._status_queue.join_thread()
        self._process.close()


class MultiprocessingRuntimeProcessSessionFactory:
    """Create fresh spawned runtime processes."""

    def create(
        self,
        runtime_paths: RuntimePaths,
    ) -> RuntimeProcessSession:
        context = multiprocessing.get_context("spawn")

        shutdown_signal = context.Event()
        status_queue = context.Queue()

        process = context.Process(
            target=_run_runtime_process,
            args=(
                runtime_paths,
                shutdown_signal,
                status_queue,
            ),
            name="audio-transcription-runtime",
            daemon=False,
        )

        return MultiprocessingRuntimeProcessSession(
            process=process,
            shutdown_signal=shutdown_signal,
            status_queue=status_queue,
        )


def _run_runtime_process(
    runtime_paths: RuntimePaths,
    shutdown_signal: _ShutdownSignal,
    status_queue: _StatusQueue,
) -> None:
    try:
        asyncio.run(
            _run_runtime_process_async(
                runtime_paths=runtime_paths,
                shutdown_signal=shutdown_signal,
                status_queue=status_queue,
            )
        )

    except Exception as exc:
        _try_publish_failure(
            status_queue,
            exc,
        )
        raise


async def _run_runtime_process_async(
    *,
    runtime_paths: RuntimePaths,
    shutdown_signal: _ShutdownSignal,
    status_queue: _StatusQueue,
) -> None:
    # Keep heavy application/native imports inside the runtime child.
    from app.main import run_application

    shutdown_event = asyncio.Event()

    shutdown_forwarder = asyncio.create_task(
        _forward_shutdown_signal(
            shutdown_signal,
            shutdown_event,
        ),
        name="runtime-shutdown-forwarder",
    )

    def notify_started() -> None:
        status_queue.put(
            RuntimeStartedEvent(),
        )

    try:
        await run_application(
            runtime_paths,
            shutdown_event=shutdown_event,
            on_started=notify_started,
        )

    finally:
        shutdown_forwarder.cancel()

        await asyncio.gather(
            shutdown_forwarder,
            return_exceptions=True,
        )


async def _forward_shutdown_signal(
    shutdown_signal: _ShutdownSignal,
    shutdown_event: asyncio.Event,
) -> None:
    while not shutdown_signal.is_set():
        await asyncio.sleep(
            _SHUTDOWN_POLL_INTERVAL_SECONDS,
        )

    shutdown_event.set()


def _try_publish_failure(
    status_queue: _StatusQueue,
    exc: Exception,
) -> None:
    message = str(exc).strip()

    failure_message = f"{type(exc).__name__}: {message}" if message else type(exc).__name__

    with contextlib.suppress(Exception):
        status_queue.put(
            RuntimeFailedEvent(
                message=failure_message,
            )
        )
