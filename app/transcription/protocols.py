from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Protocol

import numpy as np

from app.audio.contracts import SpeechSegment
from app.transcription.contracts import (
    SourcedTranscriptionResult,
    TranscriptionResult,
    TranscriptionSegmentAggregatorStats,
)

type SourcedTranscriptionResultHandler = Callable[[SourcedTranscriptionResult], None]


class WhisperSegmentProtocol(Protocol):
    """Minimal transcription segment exposed by Faster-Whisper."""

    text: str


class WhisperInfoProtocol(Protocol):
    """Minimal transcription metadata exposed by Faster-Whisper."""

    language: str


class WhisperModelProtocol(Protocol):
    """Minimal Faster-Whisper model interface required by the adapter."""

    def transcribe(
        self,
        audio: np.ndarray,
    ) -> tuple[Iterable[WhisperSegmentProtocol], WhisperInfoProtocol]:
        """Transcribe normalized audio."""


class Transcriber(Protocol):
    """Application-facing synchronous transcription contract."""

    def transcribe(self, segment: SpeechSegment) -> TranscriptionResult:
        """Transcribe one speech segment."""


class TranscriptionSegmentAggregator(Protocol):
    """Aggregate completed speech segments before transcription execution."""

    @property
    def stats(self) -> TranscriptionSegmentAggregatorStats:
        """Return an immutable snapshot of aggregation statistics."""

    def process(
        self,
        segment: SpeechSegment,
    ) -> tuple[SpeechSegment, ...]:
        """Process one completed semantic speech segment."""

    def advance(
        self,
        timestamp: float,
    ) -> tuple[SpeechSegment, ...]:
        """Advance the source timeline and emit expired pending speech."""

    def flush(self) -> tuple[SpeechSegment, ...]:
        """Emit completed speech currently held by the aggregator."""
