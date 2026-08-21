from __future__ import annotations

import logging

from app.storage.protocols import TranscriptRepository
from app.transcription.contracts import SourcedTranscriptionResult

logger = logging.getLogger(__name__)


class TranscriptRecorderImpl:
    def __init__(self, repository: TranscriptRepository) -> None:
        self._repository = repository

    def record(self, result: SourcedTranscriptionResult) -> None:
        try:
            self._repository.insert(result)
        except Exception:
            logger.exception(
                "failed to record transcript source=%s start=%.3f end=%.3f",
                result.source.value,
                result.result.start,
                result.result.end,
            )
            raise

        logger.info(
            "transcript recorded source=%s start=%.3f end=%.3f",
            result.source.value,
            result.result.start,
            result.result.end,
        )
