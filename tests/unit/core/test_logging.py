from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from pytest import MonkeyPatch

from app.core.config.enums import LogLevel
from app.core.config.models import FileLoggingSettings, LoggingSettings
from app.core.logging import configure_logging


def create_file_logging_settings(
    *,
    file_enabled: bool = False,
    path: Path = Path("logs/test.log"),
) -> FileLoggingSettings:
    return FileLoggingSettings(
        enabled=file_enabled,
        path=path,
        max_bytes=1024,
        backup_count=2,
    )


def create_logging_settings(
    *,
    file_enabled: bool = False,
    path: Path = Path("logs/test.log"),
) -> LoggingSettings:
    return LoggingSettings(
        level=LogLevel.INFO,
        file=create_file_logging_settings(
            file_enabled=file_enabled,
            path=path,
        ),
    )


def test_configure_logging_sets_configured_level(
    monkeypatch: MonkeyPatch,
) -> None:
    # Arrange
    root_logger = logging.getLogger()
    monkeypatch.setattr(root_logger, "handlers", [])
    settings = LoggingSettings(
        level=LogLevel.DEBUG,
        file=create_file_logging_settings(),
    )

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
    settings = LoggingSettings(level=LogLevel.INFO, file=create_file_logging_settings())

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
    settings = LoggingSettings(level=LogLevel.INFO, file=create_file_logging_settings())

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
    settings = LoggingSettings(level=LogLevel.INFO, file=create_file_logging_settings())

    # Act
    configure_logging(settings)
    configure_logging(settings)

    # Assert
    assert len(root_logger.handlers) == 1


def test_configure_logging_writes_to_file(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    # Arrange
    root_logger = logging.getLogger()
    monkeypatch.setattr(root_logger, "handlers", [])

    log_path = tmp_path / "nested" / "application.log"

    settings = create_logging_settings(
        file_enabled=True,
        path=log_path,
    )

    # Act
    configure_logging(settings)

    logging.getLogger("test.logger").info(
        "persistent test message",
    )

    for handler in root_logger.handlers:
        handler.flush()

    # Assert
    assert log_path.exists()
    assert "persistent test message" in log_path.read_text(
        encoding="utf-8",
    )


def test_configure_logging_writes_to_explicit_file_path(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    root_logger = logging.getLogger()
    monkeypatch.setattr(
        root_logger,
        "handlers",
        [],
    )

    configured_path = tmp_path / "logs" / "audio-transcription-service.log"

    controller_path = tmp_path / "logs" / "audio-transcription-service.controller.log"

    settings = create_logging_settings(
        file_enabled=True,
        path=configured_path,
    )

    configure_logging(
        settings,
        file_path=controller_path,
    )

    logging.getLogger("test.controller").info("controller test message")

    for handler in root_logger.handlers:
        handler.flush()

    assert controller_path.is_file()

    assert "controller test message" in controller_path.read_text(
        encoding="utf-8",
    )

    assert not configured_path.exists()


def test_configure_logging_without_stderr_keeps_file_logging(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    root_logger = logging.getLogger()
    monkeypatch.setattr(
        root_logger,
        "handlers",
        [],
    )

    monkeypatch.setattr(
        sys,
        "stderr",
        None,
    )

    log_path = tmp_path / "application.log"

    settings = create_logging_settings(
        file_enabled=True,
        path=log_path,
    )

    configure_logging(settings)

    logging.getLogger("test.windowed").info("windowed log message")

    for handler in root_logger.handlers:
        handler.flush()

    assert len(root_logger.handlers) == 1

    assert isinstance(
        root_logger.handlers[0],
        RotatingFileHandler,
    )

    assert "windowed log message" in log_path.read_text(
        encoding="utf-8",
    )


def test_explicit_file_path_preserves_rotation_settings(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    root_logger = logging.getLogger()
    monkeypatch.setattr(
        root_logger,
        "handlers",
        [],
    )

    settings = create_logging_settings(
        file_enabled=True,
        path=tmp_path / "runtime.log",
    )

    controller_path = tmp_path / "controller.log"

    configure_logging(
        settings,
        file_path=controller_path,
    )

    file_handler = next(
        handler
        for handler in root_logger.handlers
        if isinstance(
            handler,
            RotatingFileHandler,
        )
    )

    assert file_handler.maxBytes == (settings.file.max_bytes)

    assert file_handler.backupCount == (settings.file.backup_count)
