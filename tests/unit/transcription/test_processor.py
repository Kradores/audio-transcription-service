from __future__ import annotations

import numpy as np

from app.audio.contracts import AudioFormat, SpeechSegment
from app.core.config.enums import TranscriptionLanguageMode
from app.core.config.models import (
    AutoTranscriptionLanguageSettings,
    FixedTranscriptionLanguageSettings,
)
from app.transcription.contracts import (
    AudioSource,
    TranscriptionResult,
    TranscriptionWorkItem,
)
from app.transcription.processor import TranscriptionProcessorImpl


class FakeTranscriber:
    def __init__(self) -> None:
        self.received_language: str | None = None

    def transcribe(
        self,
        segment: SpeechSegment,
        *,
        language: str | None = None,
    ) -> TranscriptionResult:
        self.received_language = language

        return TranscriptionResult(
            text="text",
            language=language or "en",
            confidence=None if language is not None else 0.9,
            start=segment.timestamp,
            end=segment.timestamp + segment.duration,
        )


def create_item() -> TranscriptionWorkItem:
    segment = SpeechSegment(
        audio=np.zeros((16_000, 1), dtype=np.float32),
        timestamp=1.0,
        duration=1.0,
        format=AudioFormat(
            sample_rate=16_000,
            channels=1,
            sample_type="float32",
        ),
    )

    return TranscriptionWorkItem(
        source=AudioSource.MICROPHONE,
        segment=segment,
    )


def test_auto_mode_uses_automatic_language_detection() -> None:
    transcriber = FakeTranscriber()
    processor = TranscriptionProcessorImpl(
        transcriber=transcriber,
        language_settings=AutoTranscriptionLanguageSettings(
            mode=TranscriptionLanguageMode.AUTO,
        ),
    )

    item = create_item()

    result = processor.process(item)

    assert transcriber.received_language is None
    assert result.source is AudioSource.MICROPHONE
    assert result.result.language == "en"


def test_fixed_mode_uses_configured_language() -> None:
    transcriber = FakeTranscriber()
    processor = TranscriptionProcessorImpl(
        transcriber=transcriber,
        language_settings=FixedTranscriptionLanguageSettings(
            mode=TranscriptionLanguageMode.FIXED,
            language="ro",
        ),
    )

    item = create_item()

    result = processor.process(item)

    assert transcriber.received_language == "ro"
    assert result.source is AudioSource.MICROPHONE
    assert result.result.language == "ro"
