import pytest

from app.transcription.contracts import TranscriptionResult


def test_transcription_result_accepts_valid_values() -> None:
    result = TranscriptionResult(
        text="Hello world",
        language="en",
        confidence=0.95,
        start=10.0,
        end=12.5,
    )

    assert result.text == "Hello world"
    assert result.language == "en"
    assert result.confidence == 0.95
    assert result.start == 10.0
    assert result.end == 12.5


def test_transcription_result_allows_missing_confidence() -> None:
    result = TranscriptionResult(
        text="Hello world",
        language="en",
        confidence=None,
        start=10.0,
        end=12.5,
    )

    assert result.confidence is None


@pytest.mark.parametrize(
    "start",
    [-1.0, -0.001],
)
def test_transcription_result_rejects_negative_start(start: float) -> None:
    with pytest.raises(ValueError, match="start must not be negative"):
        TranscriptionResult(
            text="Hello",
            language="en",
            confidence=None,
            start=start,
            end=1.0,
        )


def test_transcription_result_rejects_end_before_start() -> None:
    with pytest.raises(
        ValueError,
        match="end must not be earlier than start",
    ):
        TranscriptionResult(
            text="Hello",
            language="en",
            confidence=None,
            start=10.0,
            end=9.0,
        )


@pytest.mark.parametrize(
    "confidence",
    [-0.001, 1.001],
)
def test_transcription_result_rejects_invalid_confidence(
    confidence: float,
) -> None:
    with pytest.raises(
        ValueError,
        match="confidence must be between 0.0 and 1.0",
    ):
        TranscriptionResult(
            text="Hello",
            language="en",
            confidence=confidence,
            start=0.0,
            end=1.0,
        )


def test_transcription_result_rejects_empty_language() -> None:
    with pytest.raises(ValueError, match="language must not be empty"):
        TranscriptionResult(
            text="Hello",
            language="",
            confidence=None,
            start=0.0,
            end=1.0,
        )
