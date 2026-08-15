from unittest.mock import MagicMock

import pytest

from app.storage.protocols import TranscriptRepository
from app.storage.recorder import TranscriptRecorderImpl
from app.transcription.contracts import TranscriptionResult


def test_recorder_passes_exact_result_to_repository() -> None:
    # Arrange
    repository = MagicMock(spec=TranscriptRepository)
    recorder = TranscriptRecorderImpl(repository)

    result = TranscriptionResult(
        text="hello world",
        language="en",
        confidence=0.95,
        start=10.0,
        end=12.0,
    )

    # Act
    recorder.record(result)

    # Assert
    repository.insert.assert_called_once_with(result)


def test_recorder_does_not_modify_result() -> None:
    # Arrange
    repository = MagicMock(spec=TranscriptRepository)
    recorder = TranscriptRecorderImpl(repository)

    result = TranscriptionResult(
        text="hello world",
        language="en",
        confidence=0.95,
        start=10.0,
        end=12.0,
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

    result = TranscriptionResult(
        text="hello world",
        language="en",
        confidence=None,
        start=10.0,
        end=12.0,
    )

    # Act / Assert
    with pytest.raises(RuntimeError, match="repository failed"):
        recorder.record(result)
