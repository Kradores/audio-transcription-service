from __future__ import annotations

from app.storage.protocols import TranscriptRepository
from app.transcription.contracts import TranscriptionResult


class TranscriptRecorderImpl:
    """Record completed transcription results through a repository."""

    def __init__(self, repository: TranscriptRepository) -> None:
        self._repository = repository

    def record(self, result: TranscriptionResult) -> None:
        """Record a transcription result."""

        self._repository.insert(result)
