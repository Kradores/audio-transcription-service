from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TranscriptionResult:
    """Transcription result for one speech segment."""

    text: str
    language: str
    confidence: float | None
    start: float
    end: float

    def __post_init__(self) -> None:
        if not self.language:
            raise ValueError("language must not be empty")

        if self.start < 0:
            raise ValueError("start must not be negative")

        if self.end < self.start:
            raise ValueError("end must not be earlier than start")

        if self.confidence is not None and not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0.0 and 1.0")
