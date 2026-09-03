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

    def transcribe(
        self,
        segment: SpeechSegment,
        *,
        language: str | None = None,
    ) -> TranscriptionResult:
        logger.info(
            "transcription started start=%.3f duration=%.3f language_selection=%s",
            segment.timestamp,
            segment.duration,
            language if language is not None else "auto",
        )
        started_at = time.perf_counter()
        audio = segment.audio[:, 0]

        whisper_segments, info = self._model.transcribe(
            audio,
            language=language,
        )

        segments = list(whisper_segments)

        text = " ".join(result.text.strip() for result in segments if result.text.strip())

        if language is None:
            result_language = info.language
            confidence = info.language_probability
            language_source = "detected"
        else:
            result_language = language
            confidence = None
            language_source = "explicit"

        result = TranscriptionResult(
            text=text,
            language=result_language,
            confidence=confidence,
            start=segment.timestamp,
            end=segment.timestamp + segment.duration,
        )

        logger.info(
            "transcription inference completed start=%.3f duration=%.3f "
            "inference_duration=%.3f language=%s confidence=%s "
            "language_source=%s",
            segment.timestamp,
            segment.duration,
            time.perf_counter() - started_at,
            result.language,
            (f"{result.confidence:.3f}" if result.confidence is not None else "none"),
            language_source,
        )
        logger.debug(
            "transcription result start=%.3f end=%.3f text=%r",
            result.start,
            result.end,
            result.text,
        )

        return result
