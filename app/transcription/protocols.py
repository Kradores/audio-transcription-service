from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Protocol

import numpy as np

from app.audio.contracts import SpeechSegment
from app.transcription.contracts import TranscriptionResult

type TranscriptionResultHandler = Callable[[TranscriptionResult], None]


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
