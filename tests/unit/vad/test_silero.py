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

    first_frame = _create_frame(timestamp=12.5)
    second_frame = _create_frame(timestamp=12.52)

    # Act
    adapter.process(first_frame)
    result = adapter.process(second_frame)

    # Assert
    assert result == ()
    iterator.assert_called_once()


def test_process_translates_silero_start_event() -> None:
    # Arrange
    iterator = _create_iterator()
    iterator.return_value = {"start": 0}
    adapter = SileroVADAdapter(iterator)

    first_frame = _create_frame(timestamp=12.5)
    second_frame = _create_frame(timestamp=12.52)

    # Act
    adapter.process(first_frame)
    result = adapter.process(second_frame)

    # Assert
    assert result == (
        SpeechStart(
            timestamp=12.52,
        ),
    )


def test_process_translates_silero_end_event() -> None:
    # Arrange
    iterator = _create_iterator()
    iterator.return_value = {"end": 512}
    adapter = SileroVADAdapter(iterator)

    first_frame = _create_frame(timestamp=15.0)
    second_frame = _create_frame(timestamp=15.02)

    # Act
    adapter.process(first_frame)
    result = adapter.process(second_frame)

    # Assert
    assert result == (
        SpeechEnd(
            timestamp=15.02,
        ),
    )


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

    first_frame = _create_frame(timestamp=12.5)
    second_frame = _create_frame(timestamp=12.52)

    # Act / Assert
    adapter.process(first_frame)

    with pytest.raises(ValueError, match="unexpected Silero VAD event"):
        adapter.process(second_frame)


def test_reset_delegates_to_silero_iterator() -> None:
    # Arrange
    iterator = _create_iterator()
    adapter = SileroVADAdapter(iterator)

    # Act
    adapter.reset()

    # Assert
    iterator.reset_states.assert_called_once()


def test_process_buffers_audio_until_silero_window_is_complete() -> None:
    # Arrange
    iterator = _create_iterator()
    adapter = SileroVADAdapter(iterator)

    frame = _create_frame()

    # Act
    result = adapter.process(frame)

    # Assert
    assert result == ()
    iterator.assert_not_called()


def test_process_passes_512_samples_to_iterator() -> None:
    # Arrange
    iterator = _create_iterator()
    iterator.return_value = None
    adapter = SileroVADAdapter(iterator)

    first_frame = _create_frame(timestamp=10.0)
    second_frame = _create_frame(timestamp=10.02)

    # Act
    adapter.process(first_frame)
    adapter.process(second_frame)

    # Assert
    iterator.assert_called_once()

    audio = iterator.call_args.args[0]

    assert audio.dtype == np.float32
    assert audio.shape == (512,)


def test_process_preserves_audio_order_across_silero_windows() -> None:
    # Arrange
    iterator = _create_iterator()
    iterator.return_value = None
    adapter = SileroVADAdapter(iterator)

    first_frame = _create_frame()
    first_frame.audio[:, 0] = np.arange(320, dtype=np.float32)

    second_frame = _create_frame(timestamp=10.02)
    second_frame.audio[:, 0] = np.arange(
        320,
        640,
        dtype=np.float32,
    )

    third_frame = _create_frame(timestamp=10.04)
    third_frame.audio[:, 0] = np.arange(
        640,
        960,
        dtype=np.float32,
    )

    fourth_frame = _create_frame(timestamp=10.06)
    fourth_frame.audio[:, 0] = np.arange(
        960,
        1280,
        dtype=np.float32,
    )

    # Act
    adapter.process(first_frame)
    adapter.process(second_frame)
    adapter.process(third_frame)
    adapter.process(fourth_frame)

    # Assert
    assert iterator.call_count == 2

    first_window = iterator.call_args_list[0].args[0]
    second_window = iterator.call_args_list[1].args[0]

    np.testing.assert_array_equal(
        first_window,
        np.arange(512, dtype=np.float32),
    )

    np.testing.assert_array_equal(
        second_window,
        np.arange(512, 1024, dtype=np.float32),
    )


def test_process_timestamps_silero_event_with_current_frame() -> None:
    # Arrange
    iterator = _create_iterator()
    iterator.return_value = {"start": 0}
    adapter = SileroVADAdapter(iterator)

    first_frame = _create_frame(timestamp=12.5)
    second_frame = _create_frame(timestamp=12.52)

    # Act
    first_result = adapter.process(first_frame)
    second_result = adapter.process(second_frame)

    # Assert
    assert first_result == ()

    assert second_result == (SpeechStart(timestamp=12.52),)


def test_reset_clears_pending_audio() -> None:
    # Arrange
    iterator = _create_iterator()
    adapter = SileroVADAdapter(iterator)

    first_frame = _create_frame()
    second_frame = _create_frame(timestamp=10.02)

    # Act
    adapter.process(first_frame)
    adapter.reset()
    adapter.process(second_frame)

    # Assert
    iterator.reset_states.assert_called_once()
    iterator.assert_not_called()
