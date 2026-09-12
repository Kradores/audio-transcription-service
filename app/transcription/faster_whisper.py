from __future__ import annotations

import logging
import time

from app.audio.contracts import SpeechSegment
from app.transcription.contracts import TranscriptionResult
from app.transcription.protocols import WhisperModelProtocol
from app.transcription.slow_inference_capture import SlowInferenceCapture, SlowInferenceDiagnostics

logger = logging.getLogger(__name__)


class FasterWhisperTranscriber:
    """Transcribe speech segments using a configured Faster-Whisper model."""

    def __init__(
        self,
        model: WhisperModelProtocol,
        *,
        slow_inference_capture: SlowInferenceCapture | None = None,
    ) -> None:
        self._model = model
        self._slow_inference_capture = slow_inference_capture

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

        model_setup_completed_at = time.perf_counter()

        segments = list(whisper_segments)

        decoding_completed_at = time.perf_counter()

        model_setup_duration = model_setup_completed_at - started_at
        decoding_duration = decoding_completed_at - model_setup_completed_at
        inference_duration = decoding_completed_at - started_at

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

        realtime_factor = inference_duration / segment.duration if segment.duration > 0.0 else 0.0

        logger.info(
            "transcription inference completed "
            "start=%.3f duration=%.3f "
            "inference_duration=%.3f "
            "model_setup_duration=%.3f "
            "decoding_duration=%.3f "
            "realtime_factor=%.3f "
            "output_segments=%d "
            "output_characters=%d "
            "language=%s confidence=%s "
            "language_source=%s",
            segment.timestamp,
            segment.duration,
            inference_duration,
            model_setup_duration,
            decoding_duration,
            realtime_factor,
            len(segments),
            len(text),
            result.language,
            (f"{result.confidence:.3f}" if result.confidence is not None else "none"),
            language_source,
        )

        if self._slow_inference_capture is not None:
            self._slow_inference_capture.capture_if_slow(
                segment=segment,
                diagnostics=SlowInferenceDiagnostics(
                    inference_duration_seconds=inference_duration,
                    model_setup_duration_seconds=model_setup_duration,
                    decoding_duration_seconds=decoding_duration,
                    selected_language=language,
                    result_language=result.language,
                    result_confidence=result.confidence,
                    output_segments=len(segments),
                    output_characters=len(text),
                ),
            )

        logger.debug(
            "transcription result start=%.3f end=%.3f text=%r",
            result.start,
            result.end,
            result.text,
        )

        return result
