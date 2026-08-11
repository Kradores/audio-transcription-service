from unittest.mock import AsyncMock, MagicMock

import pytest

from app.application import Application
from app.audio.protocols import AudioCapture, AudioNormalizer
from tests.unit.core.config.builders import SettingsBuilder


def test_application_exposes_provided_settings() -> None:
    # Arrange
    settings = SettingsBuilder().build()
    capture = MagicMock(spec=AudioCapture)
    normalizer = MagicMock(spec=AudioNormalizer)

    # Act
    application = Application(
        settings=settings,
        capture=capture,
        normalizer=normalizer,
    )

    # Assert
    assert application.settings is settings


def test_application_exposes_provided_audio_capture() -> None:
    # Arrange
    settings = SettingsBuilder().build()
    capture = MagicMock(spec=AudioCapture)
    normalizer = MagicMock(spec=AudioNormalizer)

    # Act
    application = Application(
        settings=settings,
        capture=capture,
        normalizer=normalizer,
    )

    # Assert
    assert application.capture is capture


def test_application_exposes_provided_audio_normalizer() -> None:
    # Arrange
    settings = SettingsBuilder().build()
    capture = MagicMock(spec=AudioCapture)
    normalizer = MagicMock(spec=AudioNormalizer)

    # Act
    application = Application(
        settings=settings,
        capture=capture,
        normalizer=normalizer,
    )

    # Assert
    assert application.normalizer is normalizer


@pytest.mark.anyio
async def test_application_start_starts_audio_capture() -> None:
    settings = SettingsBuilder().build()
    capture = AsyncMock(spec=AudioCapture)
    normalizer = MagicMock(spec=AudioNormalizer)

    # Act
    application = Application(
        settings=settings,
        capture=capture,
        normalizer=normalizer,
    )

    await application.start()

    capture.start.assert_awaited_once()


@pytest.mark.anyio
async def test_application_stop_stops_audio_capture() -> None:
    settings = SettingsBuilder().build()
    capture = AsyncMock(spec=AudioCapture)
    normalizer = MagicMock(spec=AudioNormalizer)

    application = Application(
        settings=settings,
        capture=capture,
        normalizer=normalizer,
    )

    await application.stop()

    capture.stop.assert_awaited_once()
