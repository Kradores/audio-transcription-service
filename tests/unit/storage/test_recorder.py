from unittest.mock import MagicMock

import pytest

from app.storage.protocols import TranscriptRepository
from app.storage.recorder import TranscriptRecorderImpl
from app.transcription.contracts import AudioSource, SourcedTranscriptionResult, TranscriptionResult


def test_recorder_passes_exact_result_to_repository() -> None:
    # Arrange
    repository = MagicMock(spec=TranscriptRepository)
    recorder = TranscriptRecorderImpl(repository)

    result = SourcedTranscriptionResult(
        source=AudioSource.SYSTEM_AUDIO,
        result=TranscriptionResult(
            text="hello world",
            language="en",
            confidence=0.95,
            start=10.0,
            end=12.0,
        ),
    )

    # Act
    recorder.record(result)

    # Assert
    repository.insert.assert_called_once_with(result)


def test_recorder_does_not_modify_result() -> None:
    # Arrange
    repository = MagicMock(spec=TranscriptRepository)
    recorder = TranscriptRecorderImpl(repository)

    result = SourcedTranscriptionResult(
        source=AudioSource.SYSTEM_AUDIO,
        result=TranscriptionResult(
            text="hello world",
            language="en",
            confidence=0.95,
            start=10.0,
            end=12.0,
        ),
    )

    # Act
    recorder.record(result)

    # Assert
    repository.insert.assert_called_once_with(result)


def test_recorder_propagates_repository_failure() -> None:
    # Arrange
    repository = MagicMock(spec=TranscriptRepository)
    repository.insert.side_effect = RuntimeError("repository failed")

    recorder = TranscriptRecorderImpl(repository)

    result = SourcedTranscriptionResult(
        source=AudioSource.SYSTEM_AUDIO,
        result=TranscriptionResult(
            text="hello world",
            language="en",
            confidence=None,
            start=10.0,
            end=12.0,
        ),
    )

    # Act / Assert
    with pytest.raises(RuntimeError, match="repository failed"):
        recorder.record(result)


def test_recorder_logs_success(caplog: pytest.LogCaptureFixture) -> None:
    # Arrange
    repository = MagicMock(spec=TranscriptRepository)
    recorder = TranscriptRecorderImpl(repository)

    result = SourcedTranscriptionResult(
        source=AudioSource.SYSTEM_AUDIO,
        result=TranscriptionResult(
            text="hello world",
            language="en",
            confidence=None,
            start=10.0,
            end=12.0,
        ),
    )

    # Act
    with caplog.at_level("INFO", logger="app.storage.recorder"):
        recorder.record(result)

    # Assert
    assert any(
        "transcript recorded source=system_audio start=10.000 end=12.000" in record.getMessage()
        for record in caplog.records
    )


def test_recorder_logs_failure(caplog: pytest.LogCaptureFixture) -> None:
    # Arrange
    repository = MagicMock(spec=TranscriptRepository)
    repository.insert.side_effect = RuntimeError("repository failed")
    recorder = TranscriptRecorderImpl(repository)

    result = SourcedTranscriptionResult(
        source=AudioSource.SYSTEM_AUDIO,
        result=TranscriptionResult(
            text="hello world",
            language="en",
            confidence=None,
            start=10.0,
            end=12.0,
        ),
    )

    # Act / Assert
    with (
        caplog.at_level("ERROR", logger="app.storage.recorder"),
        pytest.raises(RuntimeError, match="repository failed"),
    ):
        recorder.record(result)

    assert any(
        "failed to record transcript source=system_audio start=10.000 end=12.000"
        in record.getMessage()
        for record in caplog.records
    )
