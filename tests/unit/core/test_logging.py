from __future__ import annotations

import logging

from pytest import MonkeyPatch

from app.core.config.enums import LogLevel
from app.core.config.models import LoggingSettings
from app.core.logging import configure_logging


def test_configure_logging_sets_configured_level(
    monkeypatch: MonkeyPatch,
) -> None:
    # Arrange
    root_logger = logging.getLogger()
    monkeypatch.setattr(root_logger, "handlers", [])
    settings = LoggingSettings(level=LogLevel.DEBUG)

    # Act
    configure_logging(settings)

    # Assert
    assert root_logger.level == logging.DEBUG


def test_configure_logging_configures_console_output(
    monkeypatch: MonkeyPatch,
) -> None:
    # Arrange
    root_logger = logging.getLogger()
    monkeypatch.setattr(root_logger, "handlers", [])
    settings = LoggingSettings(level=LogLevel.INFO)

    # Act
    configure_logging(settings)

    # Assert
    assert len(root_logger.handlers) == 1
    assert isinstance(root_logger.handlers[0], logging.StreamHandler)


def test_configure_logging_formats_log_records(
    monkeypatch: MonkeyPatch,
) -> None:
    # Arrange
    root_logger = logging.getLogger()
    monkeypatch.setattr(root_logger, "handlers", [])
    settings = LoggingSettings(level=LogLevel.INFO)

    configure_logging(settings)

    handler = root_logger.handlers[0]
    record = logging.LogRecord(
        name="test.logger",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="Test message",
        args=(),
        exc_info=None,
    )

    # Act
    output = handler.format(record)

    # Assert
    assert "INFO" in output
    assert "test.logger" in output
    assert "Test message" in output
    assert "|" in output


def test_configure_logging_does_not_duplicate_handlers(
    monkeypatch: MonkeyPatch,
) -> None:
    # Arrange
    root_logger = logging.getLogger()
    monkeypatch.setattr(root_logger, "handlers", [])
    settings = LoggingSettings(level=LogLevel.INFO)

    # Act
    configure_logging(settings)
    configure_logging(settings)

    # Assert
    assert len(root_logger.handlers) == 1
