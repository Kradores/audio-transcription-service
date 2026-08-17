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

    try:
        await application.start()

        logger.info(
            "Application started successfully: %s",
            application.settings.application.name,
        )

        await event.wait()
    finally:
        await application.stop()


def main(
    config_path: Path = DEFAULT_CONFIGURATION_PATH,
) -> None:
    """Start the application."""

    try:
        asyncio.run(run_application(config_path))
    except KeyboardInterrupt:
        logger.info("Application shutdown requested")
