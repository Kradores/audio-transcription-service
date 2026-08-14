from collections.abc import Iterable

import numpy as np

from app.audio.contracts import AudioFormat, SpeechSegment
from app.transcription.faster_whisper import FasterWhisperTranscriber


class FakeWhisperSegment:
    def __init__(self, text: str) -> None:
        self.text = text


class FakeWhisperInfo:
    def __init__(self, language: str) -> None:
        self.language = language


class FakeWhisperModel:
    def __init__(
        self,
        segments: Iterable[FakeWhisperSegment],
        language: str,
    ) -> None:
        self._segments = tuple(segments)
        self._language = language
        self.received_audio: np.ndarray | None = None

    def transcribe(
        self,
        audio: np.ndarray,
    ) -> tuple[Iterable[FakeWhisperSegment], FakeWhisperInfo]:
        self.received_audio = audio

        return (
            iter(self._segments),
            FakeWhisperInfo(self._language),
        )


def create_segment() -> SpeechSegment:
    sample_rate = 16_000
    audio = np.ones(
        (sample_rate, 1),
        dtype=np.float32,
    )

    return SpeechSegment(
        audio=audio,
        timestamp=10.0,
        duration=1.0,
        format=AudioFormat(
            sample_rate=sample_rate,
            channels=1,
            sample_type="float32",
        ),
    )


def test_transcribe_returns_segment_level_result() -> None:
    # Arrange
    model = FakeWhisperModel(
        segments=[
            FakeWhisperSegment("Hello"),
            FakeWhisperSegment("world"),
        ],
        language="en",
    )
    transcriber = FasterWhisperTranscriber(model)

    segment = create_segment()

    # Act
    result = transcriber.transcribe(segment)

    # Assert
    assert result.text == "Hello world"
    assert result.language == "en"
    assert result.confidence is None
    assert result.start == 10.0
    assert result.end == 11.0


def test_transcribe_passes_segment_audio_to_model() -> None:
    # Arrange
    model = FakeWhisperModel(
        segments=[],
        language="en",
    )
    transcriber = FasterWhisperTranscriber(model)

    segment = create_segment()

    # Act
    transcriber.transcribe(segment)

    # Assert
    assert model.received_audio is not None

    np.testing.assert_array_equal(
        model.received_audio,
        segment.audio[:, 0],
    )


def test_transcribe_ignores_empty_model_segments() -> None:
    # Arrange
    model = FakeWhisperModel(
        segments=[
            FakeWhisperSegment("Hello"),
            FakeWhisperSegment(""),
            FakeWhisperSegment("  "),
            FakeWhisperSegment("world"),
        ],
        language="en",
    )
    transcriber = FasterWhisperTranscriber(model)

    # Act
    result = transcriber.transcribe(create_segment())

    # Assert
    assert result.text == "Hello world"
