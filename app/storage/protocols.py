from __future__ import annotations

from typing import Protocol

from app.transcription.contracts import TranscriptionResult


class TranscriptRepository(Protocol):
    """Persistence abstraction for completed transcription results."""

    def insert(self, result: TranscriptionResult) -> None:
        """Append a transcription result to persistent storage."""


class TranscriptRecorder(Protocol):
    """Application boundary for recording completed transcriptions."""

    def record(self, result: TranscriptionResult) -> None:
        """Record a completed transcription result."""
