from __future__ import annotations

import sqlite3
from collections.abc import Generator

import pytest

from app.storage.sqlite import SQLiteTranscriptRepository
from app.transcription.contracts import AudioSource, SourcedTranscriptionResult, TranscriptionResult


@pytest.fixture
def connection() -> Generator[sqlite3.Connection]:
    connection = sqlite3.connect(":memory:")
    try:
        yield connection
    finally:
        connection.close()


@pytest.fixture
def repository(
    connection: sqlite3.Connection,
) -> SQLiteTranscriptRepository:
    repository = SQLiteTranscriptRepository(connection)
    repository.initialize()
    return repository


def test_initialize_creates_transcripts_table(
    connection: sqlite3.Connection,
) -> None:
    # Arrange
    repository = SQLiteTranscriptRepository(connection)

    # Act
    repository.initialize()

    # Assert
    row = connection.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type = 'table' AND name = 'transcripts'
        """
    ).fetchone()

    assert row == ("transcripts",)


def test_initialize_is_idempotent(
    connection: sqlite3.Connection,
) -> None:
    # Arrange
    repository = SQLiteTranscriptRepository(connection)

    # Act
    repository.initialize()
    repository.initialize()

    # Assert
    row = connection.execute(
        """
        SELECT COUNT(*)
        FROM sqlite_master
        WHERE type = 'table' AND name = 'transcripts'
        """
    ).fetchone()

    assert row == (1,)


def test_insert_persists_transcription_result(
    repository: SQLiteTranscriptRepository,
    connection: sqlite3.Connection,
) -> None:
    # Arrange
    result = SourcedTranscriptionResult(
        source=AudioSource.SYSTEM_AUDIO,
        result=TranscriptionResult(
            text="hello world",
            language="en",
            confidence=0.95,
            start=10.5,
            end=12.75,
        ),
    )

    # Act
    repository.insert(result)

    # Assert
    row = connection.execute(
        """
        SELECT
            source,
            start_time,
            end_time,
            language,
            confidence,
            text
        FROM transcripts
        """
    ).fetchone()

    assert row == (
        "system_audio",
        10.5,
        12.75,
        "en",
        0.95,
        "hello world",
    )


def test_insert_generates_id_and_created_at(
    repository: SQLiteTranscriptRepository,
    connection: sqlite3.Connection,
) -> None:
    # Arrange
    result = SourcedTranscriptionResult(
        source=AudioSource.SYSTEM_AUDIO,
        result=TranscriptionResult(
            text="hello",
            language="en",
            confidence=None,
            start=1.0,
            end=2.0,
        ),
    )

    # Act
    repository.insert(result)

    # Assert
    row = connection.execute(
        """
        SELECT id, created_at
        FROM transcripts
        """
    ).fetchone()

    assert row is not None
    assert isinstance(row[0], int)
    assert row[0] > 0
    assert isinstance(row[1], str)
    assert row[1]


def test_insert_persists_null_confidence(
    repository: SQLiteTranscriptRepository,
    connection: sqlite3.Connection,
) -> None:
    # Arrange
    result = SourcedTranscriptionResult(
        source=AudioSource.SYSTEM_AUDIO,
        result=TranscriptionResult(
            text="hello",
            language="en",
            confidence=None,
            start=1.0,
            end=2.0,
        ),
    )

    # Act
    repository.insert(result)

    # Assert
    row = connection.execute("SELECT confidence FROM transcripts").fetchone()

    assert row == (None,)


def test_insert_is_append_only(
    repository: SQLiteTranscriptRepository,
    connection: sqlite3.Connection,
) -> None:
    # Arrange
    first = SourcedTranscriptionResult(
        source=AudioSource.SYSTEM_AUDIO,
        result=TranscriptionResult(
            text="first",
            language="en",
            confidence=0.8,
            start=1.0,
            end=2.0,
        ),
    )

    second = SourcedTranscriptionResult(
        source=AudioSource.SYSTEM_AUDIO,
        result=TranscriptionResult(
            text="second",
            language="en",
            confidence=0.9,
            start=2.0,
            end=3.0,
        ),
    )

    # Act
    repository.insert(first)
    repository.insert(second)

    # Assert
    rows = connection.execute(
        """
        SELECT start_time, end_time, text
        FROM transcripts
        ORDER BY id
        """
    ).fetchall()

    assert rows == [
        (1.0, 2.0, "first"),
        (2.0, 3.0, "second"),
    ]


def test_insert_propagates_database_failure(
    connection: sqlite3.Connection,
) -> None:
    # Arrange
    repository = SQLiteTranscriptRepository(connection)
    repository.initialize()

    connection.close()

    result = SourcedTranscriptionResult(
        source=AudioSource.SYSTEM_AUDIO,
        result=TranscriptionResult(
            text="hello",
            language="en",
            confidence=None,
            start=1.0,
            end=2.0,
        ),
    )

    # Act / Assert
    with pytest.raises(sqlite3.ProgrammingError):
        repository.insert(result)


def test_insert_commits_transaction(
    connection: sqlite3.Connection,
) -> None:
    # Arrange
    repository = SQLiteTranscriptRepository(connection)
    repository.initialize()

    result = SourcedTranscriptionResult(
        source=AudioSource.SYSTEM_AUDIO,
        result=TranscriptionResult(
            text="hello",
            language="en",
            confidence=None,
            start=1.0,
            end=2.0,
        ),
    )

    # Act
    repository.insert(result)

    # Assert
    assert connection.in_transaction is False
