from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from app.core.config.models import LoggingSettings

LOG_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"


def configure_logging(settings: LoggingSettings) -> None:
    """Configure application-wide console and persistent logging."""

    root_logger = logging.getLogger()
    root_logger.setLevel(settings.level)

    _close_handlers(root_logger)

    formatter = logging.Formatter(LOG_FORMAT)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    if not settings.file.enabled:
        return

    settings.file.path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    file_handler = RotatingFileHandler(
        filename=settings.file.path,
        maxBytes=settings.file.max_bytes,
        backupCount=settings.file.backup_count,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

    root_logger.addHandler(file_handler)


def _close_handlers(logger: logging.Logger) -> None:
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
        handler.close()
