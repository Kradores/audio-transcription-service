from unittest.mock import AsyncMock, MagicMock

import pytest

from app.application import Application
from app.audio.protocols import AudioCapture, AudioNormalizer
from app.transcription.protocols import Transcriber
from tests.unit.core.config.builders import SettingsBuilder


def test_application_exposes_provided_settings() -> None:
    # Arrange
    settings = SettingsBuilder().build()
    capture = MagicMock(spec=AudioCapture)
    normalizer = MagicMock(spec=AudioNormalizer)
    transcriber = MagicMock(spec=Transcriber)

    # Act
    application = Application(
        settings=settings,
        capture=capture,
        normalizer=normalizer,
        transcriber=transcriber,
        pipeline=AsyncMock(),
    )

    # Assert
    assert application.settings is settings


def test_application_exposes_provided_audio_capture() -> None:
    # Arrange
    settings = SettingsBuilder().build()
    capture = MagicMock(spec=AudioCapture)
    normalizer = MagicMock(spec=AudioNormalizer)
    transcriber = MagicMock(spec=Transcriber)

    # Act
    application = Application(
        settings=settings,
        capture=capture,
        normalizer=normalizer,
        transcriber=transcriber,
        pipeline=AsyncMock(),
    )

    # Assert
    assert application.capture is capture


def test_application_exposes_provided_audio_normalizer() -> None:
    # Arrange
    settings = SettingsBuilder().build()
    capture = MagicMock(spec=AudioCapture)
    normalizer = MagicMock(spec=AudioNormalizer)
    transcriber = MagicMock(spec=Transcriber)

    # Act
    application = Application(
        settings=settings,
        capture=capture,
        normalizer=normalizer,
        transcriber=transcriber,
        pipeline=AsyncMock(),
    )

    # Assert
    assert application.normalizer is normalizer


@pytest.mark.anyio
async def test_start_starts_pipeline() -> None:
    settings = SettingsBuilder().build()
    pipeline = AsyncMock()

    application = Application(
        settings=settings,
        capture=MagicMock(),
        normalizer=MagicMock(),
        transcriber=MagicMock(),
        pipeline=pipeline,
    )

    await application.start()

    pipeline.start.assert_awaited_once()


@pytest.mark.anyio
async def test_stop_stops_pipeline() -> None:
    settings = SettingsBuilder().build()
    pipeline = AsyncMock()

    application = Application(
        settings=settings,
        capture=MagicMock(),
        normalizer=MagicMock(),
        transcriber=MagicMock(),
        pipeline=pipeline,
    )

    await application.stop()

    pipeline.stop.assert_awaited_once()
