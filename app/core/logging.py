from __future__ import annotations

import logging

from app.core.config.models import LoggingSettings


def configure_logging(settings: LoggingSettings) -> None:
    """Configure application-wide logging."""

    logging.basicConfig(
        level=settings.level,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
