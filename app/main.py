from __future__ import annotations

import asyncio
import logging
import signal
from collections.abc import Callable
from pathlib import Path
from types import FrameType
from typing import Protocol

from app.application import Application
from app.core.config.models import Settings
from app.core.runtime_paths import RuntimePaths, create_development_runtime_paths

logger = logging.getLogger(__name__)


class ApplicationFactory(Protocol):
    def __call__(
        self,
        runtime_paths: RuntimePaths,
        *,
        nvidia_runtime_directory: Path | None = None,
    ) -> Application:
        """Create the application for the active platform."""


async def run_application(
    runtime_paths: RuntimePaths,
    shutdown_event: asyncio.Event | None = None,
    on_started: Callable[[Settings], None] | None = None,
    *,
    application_factory: ApplicationFactory,
    nvidia_runtime_directory: Path | None = None,
) -> None:
    """Create, run, and gracefully stop the application."""

    application = application_factory(
        runtime_paths,
        nvidia_runtime_directory=nvidia_runtime_directory,
    )
    event = shutdown_event or asyncio.Event()

    application_wait: asyncio.Task[None] | None = None
    shutdown_wait: asyncio.Task[bool] | None = None

    try:
        await application.start()

        logger.info(
            "Application started successfully: %s",
            application.settings.application.name,
        )

        if on_started is not None:
            on_started(application.settings)

        application_wait = asyncio.create_task(
            application.wait(),
            name="application-wait",
        )
        shutdown_wait = asyncio.create_task(
            event.wait(),
            name="application-shutdown-wait",
        )

        done, _ = await asyncio.wait(
            {application_wait, shutdown_wait},
            return_when=asyncio.FIRST_COMPLETED,
        )

        if application_wait in done:
            await application_wait

        if shutdown_wait in done:
            logger.info("Application shutdown requested")

    finally:
        for waiter in (application_wait, shutdown_wait):
            if waiter is not None and not waiter.done():
                waiter.cancel()

        waiters = [waiter for waiter in (application_wait, shutdown_wait) if waiter is not None]

        if waiters:
            await asyncio.gather(
                *waiters,
                return_exceptions=True,
            )

        await application.stop()


def _handle_shutdown_signal(
    shutdown_event: asyncio.Event,
    signum: int,
    frame: FrameType | None,
) -> None:
    del signum, frame
    shutdown_event.set()


async def _run_cli_application(
    runtime_paths: RuntimePaths,
) -> None:
    shutdown_event = asyncio.Event()

    previous_sigint_handler = signal.getsignal(signal.SIGINT)

    def handle_sigint(
        signum: int,
        frame: FrameType | None,
    ) -> None:
        _handle_shutdown_signal(
            shutdown_event,
            signum,
            frame,
        )

    signal.signal(
        signal.SIGINT,
        handle_sigint,
    )

    try:
        from app.platforms.windows.composition import create_windows_application

        await run_application(
            runtime_paths,
            shutdown_event=shutdown_event,
            application_factory=create_windows_application,
        )
    finally:
        signal.signal(
            signal.SIGINT,
            previous_sigint_handler,
        )


def main(
    config_path: Path | None = None,
) -> None:
    """Start the application."""

    runtime_paths = create_development_runtime_paths(
        config_path=config_path,
    )

    asyncio.run(
        _run_cli_application(runtime_paths),
    )
