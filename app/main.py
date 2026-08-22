from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from app.composition import create_application
from app.core.config.constants import DEFAULT_CONFIGURATION_PATH

logger = logging.getLogger(__name__)


async def run_application(
    config_path: Path = DEFAULT_CONFIGURATION_PATH,
    shutdown_event: asyncio.Event | None = None,
) -> None:
    """Create, run, and gracefully stop the application."""

    application = create_application(config_path)
    event = shutdown_event or asyncio.Event()

    application_wait: asyncio.Task[None] | None = None
    shutdown_wait: asyncio.Task[bool] | None = None

    try:
        await application.start()

        logger.info(
            "Application started successfully: %s",
            application.settings.application.name,
        )

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


def main(
    config_path: Path = DEFAULT_CONFIGURATION_PATH,
) -> None:
    """Start the application."""

    try:
        asyncio.run(run_application(config_path))
    except KeyboardInterrupt:
        logger.info("Application shutdown requested")
