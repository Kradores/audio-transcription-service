from __future__ import annotations

import logging

from app.storage.protocols import TranscriptRepository
from app.transcription.contracts import TranscriptionResult

logger = logging.getLogger(__name__)


class TranscriptRecorderImpl:
    """Record completed transcription results through a repository."""

    def __init__(self, repository: TranscriptRepository) -> None:
        self._repository = repository

    def record(self, result: TranscriptionResult) -> None:
        """Record a transcription result."""

        try:
            self._repository.insert(result)
        except Exception:
            logger.exception(
                "failed to record transcript start=%.3f end=%.3f",
                result.start,
                result.end,
            )
            raise

        logger.info(
            "transcript recorded start=%.3f end=%.3f",
            result.start,
            result.end,
        )
