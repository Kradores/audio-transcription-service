from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

from app.transcription.contracts import SourcedTranscriptionResult


class SQLiteTranscriptRepository:
    """Persist transcription results in SQLite."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def initialize(self) -> None:
        """Create the transcript schema when it does not already exist."""

        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS transcripts (
                id INTEGER PRIMARY KEY,
                created_at TEXT NOT NULL,
                source TEXT NOT NULL,
                start_time REAL NOT NULL,
                end_time REAL NOT NULL,
                language TEXT NOT NULL,
                confidence REAL,
                text TEXT NOT NULL
            )
            """
        )
        self._connection.commit()

    def insert(self, sourced: SourcedTranscriptionResult) -> None:
        """Append a transcription result to persistent storage."""

        result = sourced.result
        created_at = datetime.now(UTC).isoformat()

        self._connection.execute(
            """
            INSERT INTO transcripts (
                created_at,
                source,
                start_time,
                end_time,
                language,
                confidence,
                text
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                created_at,
                sourced.source.value,
                result.start,
                result.end,
                result.language,
                result.confidence,
                result.text,
            ),
        )
        self._connection.commit()
