from __future__ import annotations

from typing import Protocol

from app.transcription.contracts import SourcedTranscriptionResult


class TranscriptRepository(Protocol):
    def insert(self, result: SourcedTranscriptionResult) -> None:
        """Append a sourced transcription result to persistent storage."""


class TranscriptRecorder(Protocol):
    def record(self, result: SourcedTranscriptionResult) -> None:
        """Record a completed sourced transcription result."""
