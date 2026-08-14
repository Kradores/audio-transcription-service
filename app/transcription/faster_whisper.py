from __future__ import annotations

from app.audio.contracts import SpeechSegment
from app.transcription.contracts import TranscriptionResult
from app.transcription.protocols import WhisperModelProtocol


class FasterWhisperTranscriber:
    """Transcribe speech segments using a configured Faster-Whisper model."""

    def __init__(self, model: WhisperModelProtocol) -> None:
        self._model = model

    def transcribe(self, segment: SpeechSegment) -> TranscriptionResult:
        audio = segment.audio[:, 0]

        whisper_segments, info = self._model.transcribe(audio)

        segments = list(whisper_segments)

        text = " ".join(result.text.strip() for result in segments if result.text.strip())

        return TranscriptionResult(
            text=text,
            language=info.language,
            confidence=None,
            start=segment.timestamp,
            end=segment.timestamp + segment.duration,
        )
