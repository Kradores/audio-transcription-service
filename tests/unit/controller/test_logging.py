from pathlib import Path
from unittest.mock import patch

from app.controller.logging import (
    configure_controller_logging,
    derive_controller_log_path,
)
from app.core.config.enums import LogLevel
from app.core.config.models import (
    FileLoggingSettings,
    LoggingSettings,
)


def test_derives_controller_log_path() -> None:
    runtime_path = Path("logs") / "audio-transcription-service.log"

    result = derive_controller_log_path(runtime_path)

    assert result == (Path("logs") / "audio-transcription-service.controller.log")


def test_derives_controller_log_path_without_suffix() -> None:
    runtime_path = Path("logs") / "application"

    result = derive_controller_log_path(runtime_path)

    assert result == (Path("logs") / "application.controller")


def test_configure_controller_logging_uses_sibling_path(
    tmp_path: Path,
) -> None:
    runtime_log_path = tmp_path / "logs" / "audio-transcription-service.log"

    settings = LoggingSettings(
        level=LogLevel.INFO,
        file=FileLoggingSettings(
            enabled=True,
            path=runtime_log_path,
            max_bytes=1024,
            backup_count=2,
        ),
    )

    with patch("app.controller.logging.configure_logging") as configure:
        result = configure_controller_logging(settings)

    expected = tmp_path / "logs" / "audio-transcription-service.controller.log"

    assert result == expected

    configure.assert_called_once_with(
        settings,
        file_path=expected,
    )


def test_configure_controller_logging_without_file_logging(
    tmp_path: Path,
) -> None:
    settings = LoggingSettings(
        level=LogLevel.INFO,
        file=FileLoggingSettings(
            enabled=False,
            path=tmp_path / "runtime.log",
            max_bytes=1024,
            backup_count=2,
        ),
    )

    with patch("app.controller.logging.configure_logging") as configure:
        result = configure_controller_logging(settings)

    assert result is None

    configure.assert_called_once_with(
        settings,
        file_path=None,
    )
