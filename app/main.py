from __future__ import annotations

import logging
from pathlib import Path

from app.application import Application
from app.composition import create_application
from app.core.config.constants import DEFAULT_CONFIGURATION_PATH

logger = logging.getLogger(__name__)


def main(
    config_path: Path = DEFAULT_CONFIGURATION_PATH,
) -> None:
    """Start the application."""

    application: Application = create_application(config_path)

    logger.info(
        "Application started successfully: %s",
        application.settings.application.name,
    )
