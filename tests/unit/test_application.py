import sqlite3
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
        database=MagicMock(spec=sqlite3.Connection),
        recorder=MagicMock(),
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
        database=MagicMock(spec=sqlite3.Connection),
        recorder=MagicMock(),
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
        database=MagicMock(spec=sqlite3.Connection),
        recorder=MagicMock(),
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
        database=MagicMock(spec=sqlite3.Connection),
        recorder=MagicMock(),
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
        database=MagicMock(spec=sqlite3.Connection),
        recorder=MagicMock(),
    )

    await application.stop()

    pipeline.stop.assert_awaited_once()


@pytest.mark.anyio
async def test_stop_closes_database() -> None:
    settings = SettingsBuilder().build()
    pipeline = AsyncMock()
    database = MagicMock(spec=sqlite3.Connection)

    application = Application(
        settings=settings,
        capture=MagicMock(),
        normalizer=MagicMock(),
        transcriber=MagicMock(),
        pipeline=pipeline,
        database=database,
        recorder=MagicMock(),
    )

    await application.stop()

    pipeline.stop.assert_awaited_once()
    database.close.assert_called_once_with()


@pytest.mark.anyio
async def test_stop_stops_pipeline_before_closing_database() -> None:
    settings = SettingsBuilder().build()
    events: list[str] = []

    pipeline = AsyncMock()

    async def stop_pipeline() -> None:
        events.append("pipeline-stop")

    pipeline.stop.side_effect = stop_pipeline

    database = MagicMock(spec=sqlite3.Connection)
    database.close.side_effect = lambda: events.append("database-close")

    application = Application(
        settings=settings,
        capture=MagicMock(),
        normalizer=MagicMock(),
        transcriber=MagicMock(),
        pipeline=pipeline,
        database=database,
        recorder=MagicMock(),
    )

    await application.stop()

    assert events == [
        "pipeline-stop",
        "database-close",
    ]
