from unittest.mock import MagicMock

from app.application import Application
from app.audio.protocols import AudioCapture
from tests.unit.core.config.builders import SettingsBuilder


def test_application_exposes_provided_settings() -> None:
    # Arrange
    settings = SettingsBuilder().build()
    capture = MagicMock(spec=AudioCapture)

    # Act
    application = Application(
        settings=settings,
        capture=capture,
    )

    # Assert
    assert application.settings is settings


def test_application_exposes_provided_audio_capture() -> None:
    # Arrange
    settings = SettingsBuilder().build()
    capture = MagicMock(spec=AudioCapture)

    # Act
    application = Application(
        settings=settings,
        capture=capture,
    )

    # Assert
    assert application.capture is capture
