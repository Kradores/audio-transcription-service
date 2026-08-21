import sqlite3
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.application import Application
from app.audio.protocols import AudioCapture, AudioNormalizer
from app.services.transcription_executor import TranscriptionExecutor
from tests.unit.core.config.builders import SettingsBuilder


def create_transcription_executor_mock() -> MagicMock:
    executor = MagicMock(spec=TranscriptionExecutor)
    executor.start = AsyncMock()
    executor.stop = AsyncMock()
    return executor


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
        pipeline=AsyncMock(),
        transcription_executor=create_transcription_executor_mock(),
        database=MagicMock(spec=sqlite3.Connection),
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
        pipeline=AsyncMock(),
        transcription_executor=create_transcription_executor_mock(),
        database=MagicMock(spec=sqlite3.Connection),
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
        pipeline=AsyncMock(),
        transcription_executor=create_transcription_executor_mock(),
        database=MagicMock(spec=sqlite3.Connection),
    )

    # Assert
    assert application.normalizer is normalizer


@pytest.mark.anyio
async def test_start_starts_executor_before_pipeline() -> None:
    # Arrange
    settings = SettingsBuilder().build()
    events: list[str] = []

    transcription_executor = create_transcription_executor_mock()
    pipeline = AsyncMock()

    async def start_executor() -> None:
        events.append("executor-start")

    async def start_pipeline() -> None:
        events.append("pipeline-start")

    transcription_executor.start.side_effect = start_executor
    pipeline.start.side_effect = start_pipeline

    application = Application(
        settings=settings,
        capture=MagicMock(),
        normalizer=MagicMock(),
        pipeline=pipeline,
        transcription_executor=transcription_executor,
        database=MagicMock(spec=sqlite3.Connection),
    )

    # Act
    await application.start()

    # Assert
    assert events == [
        "executor-start",
        "pipeline-start",
    ]


@pytest.mark.anyio
async def test_stop_stops_pipeline_then_executor_before_closing_database() -> None:
    # Arrange
    settings = SettingsBuilder().build()
    events: list[str] = []

    pipeline = AsyncMock()
    transcription_executor = create_transcription_executor_mock()

    async def stop_pipeline() -> None:
        events.append("pipeline-stop")

    async def stop_executor() -> None:
        events.append("executor-stop")

    pipeline.stop.side_effect = stop_pipeline
    transcription_executor.stop.side_effect = stop_executor

    database = MagicMock(spec=sqlite3.Connection)
    database.close.side_effect = lambda: events.append("database-close")

    application = Application(
        settings=settings,
        capture=MagicMock(),
        normalizer=MagicMock(),
        pipeline=pipeline,
        transcription_executor=transcription_executor,
        database=database,
    )

    # Act
    await application.stop()

    # Assert
    assert events == [
        "pipeline-stop",
        "executor-stop",
        "database-close",
    ]


@pytest.mark.anyio
async def test_stop_closes_database() -> None:
    settings = SettingsBuilder().build()
    pipeline = AsyncMock()
    database = MagicMock(spec=sqlite3.Connection)

    application = Application(
        settings=settings,
        capture=MagicMock(),
        normalizer=MagicMock(),
        pipeline=pipeline,
        transcription_executor=create_transcription_executor_mock(),
        database=database,
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
        pipeline=pipeline,
        transcription_executor=create_transcription_executor_mock(),
        database=database,
    )

    await application.stop()

    assert events == [
        "pipeline-stop",
        "database-close",
    ]
