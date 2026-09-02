from __future__ import annotations

import logging
import time

from app.audio.contracts import SpeechSegment
from app.transcription.contracts import TranscriptionResult
from app.transcription.protocols import WhisperModelProtocol

logger = logging.getLogger(__name__)


class FasterWhisperTranscriber:
    """Transcribe speech segments using a configured Faster-Whisper model."""

    def __init__(self, model: WhisperModelProtocol) -> None:
        self._model = model

    def transcribe(self, segment: SpeechSegment) -> TranscriptionResult:
        logger.info(
            "transcription started start=%.3f duration=%.3f",
            segment.timestamp,
            segment.duration,
        )
        started_at = time.perf_counter()
        audio = segment.audio[:, 0]

        whisper_segments, info = self._model.transcribe(audio)

        segments = list(whisper_segments)

        text = " ".join(result.text.strip() for result in segments if result.text.strip())

        result = TranscriptionResult(
            text=text,
            language=info.language,
            confidence=info.language_probability,
            start=segment.timestamp,
            end=segment.timestamp + segment.duration,
        )

        logger.info(
            "transcription inference completed start=%.3f duration=%.3f "
            "inference_duration=%.3f language=%s language_probability=%.3f",
            segment.timestamp,
            segment.duration,
            time.perf_counter() - started_at,
            result.language,
            info.language_probability,
        )
        logger.debug(
            "transcription result start=%.3f end=%.3f text=%r",
            result.start,
            result.end,
            result.text,
        )

        return result
