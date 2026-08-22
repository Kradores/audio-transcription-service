import sqlite3
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.application import Application
from app.services.conversation_pipeline import ConversationPipeline
from tests.unit.core.config.builders import SettingsBuilder


def create_conversation_mock() -> MagicMock:
    conversation = MagicMock(spec=ConversationPipeline)
    conversation.start = AsyncMock()
    conversation.stop = AsyncMock()
    conversation.wait = AsyncMock()
    return conversation


def test_application_exposes_provided_settings() -> None:
    # Arrange
    settings = SettingsBuilder().build()

    # Act
    application = Application(
        settings=settings,
        conversation_pipeline=create_conversation_mock(),
        database=MagicMock(spec=sqlite3.Connection),
    )

    # Assert
    assert application.settings is settings


# tests/unit/test_application.py


@pytest.mark.anyio
async def test_start_starts_conversation_pipeline() -> None:
    conversation = create_conversation_mock()

    application = Application(
        settings=SettingsBuilder().build(),
        conversation_pipeline=conversation,
        database=MagicMock(spec=sqlite3.Connection),
    )

    await application.start()

    conversation.start.assert_awaited_once()


# tests/unit/test_application.py


@pytest.mark.anyio
async def test_stop_stops_conversation_before_closing_database() -> None:
    events: list[str] = []

    conversation = create_conversation_mock()

    async def stop_conversation() -> None:
        events.append("conversation-stop")

    conversation.stop.side_effect = stop_conversation

    database = MagicMock(spec=sqlite3.Connection)
    database.close.side_effect = lambda: events.append("database-close")

    application = Application(
        settings=SettingsBuilder().build(),
        conversation_pipeline=conversation,
        database=database,
    )

    await application.stop()

    assert events == [
        "conversation-stop",
        "database-close",
    ]


# tests/unit/test_application.py


@pytest.mark.anyio
async def test_stop_closes_database_when_conversation_stop_fails() -> None:
    conversation = create_conversation_mock()
    conversation.stop.side_effect = RuntimeError(
        "conversation shutdown failed",
    )

    database = MagicMock(spec=sqlite3.Connection)

    application = Application(
        settings=SettingsBuilder().build(),
        conversation_pipeline=conversation,
        database=database,
    )

    with pytest.raises(
        RuntimeError,
        match="conversation shutdown failed",
    ):
        await application.stop()

    database.close.assert_called_once_with()


@pytest.mark.anyio
async def test_stop_closes_database() -> None:
    settings = SettingsBuilder().build()
    database = MagicMock(spec=sqlite3.Connection)

    application = Application(
        settings=settings,
        conversation_pipeline=create_conversation_mock(),
        database=database,
    )

    await application.stop()

    database.close.assert_called_once_with()


@pytest.mark.anyio
async def test_wait_waits_for_conversation_pipeline() -> None:
    # Arrange
    conversation = create_conversation_mock()

    application = Application(
        settings=SettingsBuilder().build(),
        conversation_pipeline=conversation,
        database=MagicMock(spec=sqlite3.Connection),
    )

    # Act
    await application.wait()

    # Assert
    conversation.wait.assert_awaited_once()
