from __future__ import annotations

from pathlib import Path

from app.application import Application
from app.core.config.constants import DEFAULT_CONFIGURATION_PATH
from app.core.config.loader import ConfigurationLoader
from app.core.logging import configure_logging


def create_application(
    config_path: Path = DEFAULT_CONFIGURATION_PATH,
) -> Application:
    """Create and configure the application."""

    settings = ConfigurationLoader(config_path).load()

    configure_logging(settings.logging)

    return Application(settings)
