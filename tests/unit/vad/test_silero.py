from unittest.mock import MagicMock

import numpy as np
import pytest

from app.audio.contracts import (
    AudioFormat,
    ProcessingAudioFrame,
    SpeechEnd,
    SpeechStart,
)
from app.vad.protocols import SileroVADIterator
from app.vad.silero import SileroVADAdapter


def _create_frame(
    *,
    sample_rate: int = 16_000,
    channels: int = 1,
    timestamp: float = 10.0,
) -> ProcessingAudioFrame:
    sample_count = round(sample_rate * 0.020)

    return ProcessingAudioFrame(
        audio=np.zeros((sample_count, channels), dtype=np.float32),
        timestamp=timestamp,
        format=AudioFormat(
            sample_rate=sample_rate,
            channels=channels,
            sample_type="float32",
        ),
    )


def _create_iterator() -> MagicMock:
    return MagicMock(spec=SileroVADIterator)


def test_process_returns_no_events_when_silero_returns_none() -> None:
    # Arrange
    iterator = _create_iterator()
    iterator.return_value = None
    adapter = SileroVADAdapter(iterator)

    frame = _create_frame()

    # Act
    result = adapter.process(frame)

    # Assert
    assert result == ()
    iterator.assert_called_once()


def test_process_translates_silero_start_event() -> None:
    # Arrange
    iterator = _create_iterator()
    iterator.return_value = {"start": 0}
    adapter = SileroVADAdapter(iterator)

    frame = _create_frame(timestamp=12.5)

    # Act
    result = adapter.process(frame)

    # Assert
    assert result == (
        SpeechStart(
            timestamp=12.5,
        ),
    )


def test_process_translates_silero_end_event() -> None:
    # Arrange
    iterator = _create_iterator()
    iterator.return_value = {"end": 320}
    adapter = SileroVADAdapter(iterator)

    frame = _create_frame(timestamp=15.0)

    # Act
    result = adapter.process(frame)

    # Assert
    assert result == (
        SpeechEnd(
            timestamp=15.0,
        ),
    )


def test_process_passes_mono_float32_audio_to_iterator() -> None:
    # Arrange
    iterator = _create_iterator()
    iterator.return_value = None
    adapter = SileroVADAdapter(iterator)

    frame = _create_frame()

    # Act
    adapter.process(frame)

    # Assert
    audio = iterator.call_args.args[0]

    assert audio.dtype == np.float32
    assert audio.shape == (320,)


def test_process_rejects_non_16khz_audio() -> None:
    # Arrange
    iterator = _create_iterator()
    adapter = SileroVADAdapter(iterator)

    frame = _create_frame(sample_rate=8_000)

    # Act / Assert
    with pytest.raises(
        ValueError,
        match="Silero VAD requires a 16 kHz processing sample rate",
    ):
        adapter.process(frame)

    iterator.assert_not_called()


def test_process_rejects_stereo_audio() -> None:
    # Arrange
    iterator = _create_iterator()
    adapter = SileroVADAdapter(iterator)

    frame = _create_frame(channels=2)

    # Act / Assert
    with pytest.raises(
        ValueError,
        match="Silero VAD requires mono processing audio",
    ):
        adapter.process(frame)

    iterator.assert_not_called()


def test_process_rejects_unknown_silero_event() -> None:
    # Arrange
    iterator = _create_iterator()
    iterator.return_value = {"unexpected": 123}
    adapter = SileroVADAdapter(iterator)

    frame = _create_frame()

    # Act / Assert
    with pytest.raises(ValueError, match="unexpected Silero VAD event"):
        adapter.process(frame)


def test_reset_delegates_to_silero_iterator() -> None:
    # Arrange
    iterator = _create_iterator()
    adapter = SileroVADAdapter(iterator)

    # Act
    adapter.reset()

    # Assert
    iterator.reset_states.assert_called_once()
