import logging
from collections.abc import Iterable
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from app.audio.contracts import AudioFormat, SpeechSegment
from app.transcription.faster_whisper import FasterWhisperTranscriber
from app.transcription.slow_inference_capture import SlowInferenceCapture


class FakeWhisperSegment:
    def __init__(self, text: str) -> None:
        self.text = text


class FakeWhisperInfo:
    def __init__(
        self,
        language: str,
        language_probability: float,
    ) -> None:
        self.language = language
        self.language_probability = language_probability


class FakeWhisperModel:
    def __init__(
        self,
        segments: Iterable[FakeWhisperSegment],
        language: str,
        language_probability: float = 0.9,
    ) -> None:
        self._segments = tuple(segments)
        self._language = language
        self._language_probability = language_probability
        self.received_audio: np.ndarray | None = None
        self.received_language: str | None = None

    def transcribe(
        self,
        audio: np.ndarray,
        *,
        language: str | None = None,
    ) -> tuple[Iterable[FakeWhisperSegment], FakeWhisperInfo]:
        self.received_audio = audio
        self.received_language = language

        return (
            iter(self._segments),
            FakeWhisperInfo(
                self._language,
                self._language_probability,
            ),
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
    assert result.confidence == 0.9
    assert model.received_language is None
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


def test_transcribe_logs_inference_timing_and_result(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Arrange
    model = FakeWhisperModel(
        segments=[FakeWhisperSegment("Hello")],
        language="en",
    )
    transcriber = FasterWhisperTranscriber(model)

    # Act
    with caplog.at_level("INFO", logger="app.transcription.faster_whisper"):
        result = transcriber.transcribe(create_segment())

    # Assert
    messages = [record.getMessage() for record in caplog.records]
    assert any(
        "transcription started start=10.000 duration=1.000" in message
        and "language_selection=auto" in message
        for message in messages
    )
    assert any(
        "transcription inference completed" in message
        and "confidence=0.900" in message
        and "language_source=detected" in message
        for message in messages
    )
    assert result.text == "Hello"


def test_transcribe_passes_explicit_language_to_model() -> None:
    # Arrange
    model = FakeWhisperModel(
        segments=[FakeWhisperSegment("Da.")],
        language="ro",
        language_probability=1.0,
    )
    transcriber = FasterWhisperTranscriber(model)

    # Act
    result = transcriber.transcribe(
        create_segment(),
        language="ro",
    )

    # Assert
    assert model.received_language == "ro"
    assert result.text == "Da."
    assert result.language == "ro"
    assert result.confidence is None


def test_transcribe_logs_explicit_language_without_detection_confidence(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Arrange
    model = FakeWhisperModel(
        segments=[FakeWhisperSegment("Da.")],
        language="ro",
        language_probability=1.0,
    )
    transcriber = FasterWhisperTranscriber(model)

    # Act
    with caplog.at_level("INFO", logger="app.transcription.faster_whisper"):
        transcriber.transcribe(
            create_segment(),
            language="ro",
        )

    # Assert
    messages = [record.getMessage() for record in caplog.records]
    assert any("language_selection=ro" in message for message in messages)
    assert any(
        "confidence=none" in message and "language_source=explicit" in message
        for message in messages
    )


def test_transcribe_logs_inference_phase_diagnostics(
    caplog: pytest.LogCaptureFixture,
) -> None:
    model = FakeWhisperModel(
        segments=[
            FakeWhisperSegment("Hello"),
            FakeWhisperSegment("world"),
        ],
        language="en",
    )
    transcriber = FasterWhisperTranscriber(model)

    with caplog.at_level(
        logging.INFO,
        logger="app.transcription.faster_whisper",
    ):
        transcriber.transcribe(create_segment())

    message = caplog.records[-1].getMessage()

    assert "inference_duration=" in message
    assert "model_setup_duration=" in message
    assert "decoding_duration=" in message
    assert "realtime_factor=" in message
    assert "output_segments=2" in message
    assert "output_characters=11" in message


def test_transcribe_reports_timing_and_result_to_slow_inference_capture() -> None:
    model = FakeWhisperModel(
        segments=[
            FakeWhisperSegment("Hello"),
            FakeWhisperSegment("world"),
        ],
        language="en",
        language_probability=0.93,
    )

    slow_inference_capture = MagicMock(
        spec=SlowInferenceCapture,
    )

    transcriber = FasterWhisperTranscriber(
        model,
        slow_inference_capture=slow_inference_capture,
    )

    segment = create_segment()

    with patch(
        "app.transcription.faster_whisper.time.perf_counter",
        side_effect=[
            10.0,
            10.1,
            12.5,
        ],
    ):
        transcriber.transcribe(segment)

    slow_inference_capture.capture_if_slow.assert_called_once()

    call_kwargs = slow_inference_capture.capture_if_slow.call_args.kwargs

    assert call_kwargs["segment"] is segment

    diagnostics = call_kwargs["diagnostics"]

    assert diagnostics.inference_duration_seconds == pytest.approx(2.5)
    assert diagnostics.model_setup_duration_seconds == pytest.approx(0.1)
    assert diagnostics.decoding_duration_seconds == pytest.approx(2.4)

    assert diagnostics.selected_language is None
    assert diagnostics.result_language == "en"
    assert diagnostics.result_confidence == pytest.approx(0.93)

    assert diagnostics.output_segments == 2
    assert diagnostics.output_characters == 11
