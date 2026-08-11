import numpy as np
import pytest

from app.audio.contracts import AudioFormat, AudioFrame
from app.audio.normalizer import AudioNormalizerImpl
from app.core.config.models import AudioProcessingSettings


def create_settings(
    *,
    sample_rate: int = 16_000,
    channels: int = 1,
) -> AudioProcessingSettings:
    return AudioProcessingSettings(
        sample_rate=sample_rate,
        channels=channels,
    )


def create_frame(
    audio: np.ndarray,
    *,
    sample_rate: int = 16_000,
    timestamp: float = 0.0,
) -> AudioFrame:
    return AudioFrame(
        audio=audio,
        timestamp=timestamp,
        format=AudioFormat(
            sample_rate=sample_rate,
            channels=audio.shape[1],
            sample_type="int16",
        ),
    )


def test_normalizer_emits_one_processing_frame_for_20_ms_input() -> None:
    # Arrange
    normalizer = AudioNormalizerImpl(
        create_settings(),
    )
    audio = np.arange(320, dtype=np.int16).reshape(320, 1)
    frame = create_frame(audio)

    # Act
    output = normalizer.process(frame)

    # Assert
    assert len(output) == 1
    assert output[0].audio.shape == (320, 1)
    assert output[0].audio.dtype == np.float32
    np.testing.assert_allclose(
        output[0].audio[:, 0],
        audio[:, 0] / 32768.0,
    )


def test_normalizer_buffers_incomplete_frame() -> None:
    # Arrange
    normalizer = AudioNormalizerImpl(
        create_settings(),
    )
    audio = np.ones((160, 1), dtype=np.int16)
    frame = create_frame(audio)

    # Act
    output = normalizer.process(frame)

    # Assert
    assert output == ()


def test_normalizer_combines_partial_input_frames() -> None:
    # Arrange
    normalizer = AudioNormalizerImpl(
        create_settings(),
    )

    first = create_frame(
        np.ones((160, 1), dtype=np.int16),
    )
    second = create_frame(
        np.full((160, 1), 2, dtype=np.int16),
        timestamp=0.01,
    )

    # Act
    first_output = normalizer.process(first)
    second_output = normalizer.process(second)

    # Assert
    assert first_output == ()
    assert len(second_output) == 1

    np.testing.assert_array_equal(
        second_output[0].audio[:160, 0],
        np.full(160, 1 / 32768.0, dtype=np.float32),
    )
    np.testing.assert_array_equal(
        second_output[0].audio[160:, 0],
        np.full(160, 2 / 32768.0, dtype=np.float32),
    )


def test_normalizer_emits_multiple_frames_from_large_input() -> None:
    # Arrange
    normalizer = AudioNormalizerImpl(
        create_settings(),
    )
    audio = np.arange(640, dtype=np.int16).reshape(640, 1)
    frame = create_frame(audio)

    # Act
    output = normalizer.process(frame)

    # Assert
    assert len(output) == 2

    np.testing.assert_allclose(
        output[0].audio[:, 0],
        audio[:320, 0] / 32768.0,
    )
    np.testing.assert_allclose(
        output[1].audio[:, 0],
        audio[320:, 0] / 32768.0,
    )


def test_normalizer_preserves_timestamp_for_first_output_frame() -> None:
    # Arrange
    normalizer = AudioNormalizerImpl(
        create_settings(),
    )
    frame = create_frame(
        np.zeros((320, 1), dtype=np.int16),
        timestamp=12.5,
    )

    # Act
    output = normalizer.process(frame)

    # Assert
    assert len(output) == 1
    assert output[0].timestamp == pytest.approx(12.5)


def test_normalizer_output_timestamps_advance_by_20_ms() -> None:
    # Arrange
    normalizer = AudioNormalizerImpl(
        create_settings(),
    )
    frame = create_frame(
        np.zeros((640, 1), dtype=np.int16),
        timestamp=12.5,
    )

    # Act
    output = normalizer.process(frame)

    # Assert
    assert len(output) == 2
    assert output[0].timestamp == pytest.approx(12.5)
    assert output[1].timestamp == pytest.approx(12.52)


def test_normalizer_flush_discards_incomplete_audio() -> None:
    # Arrange
    normalizer = AudioNormalizerImpl(
        create_settings(),
    )
    frame = create_frame(
        np.zeros((160, 1), dtype=np.int16),
    )

    # Act
    output = normalizer.process(frame)
    normalizer.flush()

    # Assert
    assert output == ()

    next_output = normalizer.process(
        create_frame(
            np.zeros((160, 1), dtype=np.int16),
        ),
    )

    assert next_output == ()


def test_normalizer_rejects_unsupported_sample_rate() -> None:
    # Arrange
    normalizer = AudioNormalizerImpl(
        create_settings(),
    )
    unsupported_format = AudioFormat(
        sample_rate=48_000,
        channels=1,
        sample_type="int16",
    )
    frame = AudioFrame(
        audio=np.zeros((960, 1), dtype=np.int16),
        timestamp=0.0,
        format=unsupported_format,
    )

    # Act / Assert
    with pytest.raises(ValueError, match="sample rate"):
        normalizer.process(frame)


def test_normalizer_downmixes_stereo_to_mono() -> None:
    # Arrange
    normalizer = AudioNormalizerImpl(
        create_settings(),
    )
    stereo_format = AudioFormat(
        sample_rate=16_000,
        channels=2,
        sample_type="int16",
    )
    audio = np.column_stack(
        (
            np.full(320, 1000, dtype=np.int16),
            np.full(320, 3000, dtype=np.int16),
        ),
    )
    frame = AudioFrame(
        audio=audio,
        timestamp=0.0,
        format=stereo_format,
    )

    # Act
    output = normalizer.process(frame)

    # Assert
    assert len(output) == 1
    assert output[0].audio.shape == (320, 1)
    np.testing.assert_allclose(
        output[0].audio[:, 0],
        2000 / 32768.0,
    )


def test_normalizer_continues_timestamp_from_buffered_audio() -> None:
    # Arrange
    normalizer = AudioNormalizerImpl(
        create_settings(),
    )

    first = create_frame(
        np.zeros((400, 1), dtype=np.int16),
        timestamp=10.0,
    )
    second = create_frame(
        np.zeros((240, 1), dtype=np.int16),
        timestamp=10.025,
    )

    # Act
    first_output = normalizer.process(first)
    second_output = normalizer.process(second)

    # Assert
    assert len(first_output) == 1
    assert len(second_output) == 1

    assert first_output[0].timestamp == pytest.approx(10.0)
    assert second_output[0].timestamp == pytest.approx(10.02)


def test_normalizer_preserves_leftover_samples_between_frames() -> None:
    # Arrange
    normalizer = AudioNormalizerImpl(
        create_settings(),
    )

    first = create_frame(
        np.ones((400, 1), dtype=np.int16),
    )
    second = create_frame(
        np.full((240, 1), 2, dtype=np.int16),
    )

    # Act
    first_output = normalizer.process(first)
    second_output = normalizer.process(second)

    # Assert
    assert len(first_output) == 1
    assert len(second_output) == 1

    np.testing.assert_array_equal(
        first_output[0].audio[:, 0],
        np.full(320, 1 / 32768.0, dtype=np.float32),
    )

    np.testing.assert_array_equal(
        second_output[0].audio[:, 0],
        np.concatenate(
            (
                np.full(80, 1 / 32768.0, dtype=np.float32),
                np.full(240, 2 / 32768.0, dtype=np.float32),
            ),
        ),
    )


def test_normalizer_derives_frame_size_from_processing_sample_rate() -> None:
    # Arrange
    settings = create_settings(sample_rate=48_000)
    normalizer = AudioNormalizerImpl(settings)

    audio = np.zeros((960, 1), dtype=np.int16)

    frame = AudioFrame(
        audio=audio,
        timestamp=0.0,
        format=AudioFormat(
            sample_rate=48_000,
            channels=1,
            sample_type="int16",
        ),
    )

    # Act
    output = normalizer.process(frame)

    # Assert
    assert len(output) == 1
    assert output[0].audio.shape == (960, 1)
    assert output[0].format.sample_rate == 48_000
    assert output[0].format.channels == 1
    assert output[0].format.sample_type == "float32"


def test_normalizer_upmixes_mono_to_stereo() -> None:
    # Arrange
    normalizer = AudioNormalizerImpl(
        create_settings(channels=2),
    )
    audio = np.column_stack(
        (np.full(320, 1000, dtype=np.int16),),
    )
    frame = AudioFrame(
        audio=audio,
        timestamp=0.0,
        format=AudioFormat(
            sample_rate=16_000,
            channels=1,
            sample_type="int16",
        ),
    )

    # Act
    output = normalizer.process(frame)

    # Assert
    assert len(output) == 1
    assert output[0].audio.shape == (320, 2)

    expected = np.full(
        (320, 2),
        1000 / 32768.0,
        dtype=np.float32,
    )

    np.testing.assert_allclose(
        output[0].audio,
        expected,
    )


def test_normalizer_preserves_stereo_when_target_is_stereo() -> None:
    # Arrange
    normalizer = AudioNormalizerImpl(
        create_settings(channels=2),
    )
    audio = np.column_stack(
        (
            np.full(320, 1000, dtype=np.int16),
            np.full(320, 3000, dtype=np.int16),
        ),
    )
    frame = AudioFrame(
        audio=audio,
        timestamp=0.0,
        format=AudioFormat(
            sample_rate=16_000,
            channels=2,
            sample_type="int16",
        ),
    )

    # Act
    output = normalizer.process(frame)

    # Assert
    assert len(output) == 1
    assert output[0].audio.shape == (320, 2)

    expected = np.column_stack(
        (
            np.full(320, 1000 / 32768.0, dtype=np.float32),
            np.full(320, 3000 / 32768.0, dtype=np.float32),
        ),
    )

    np.testing.assert_allclose(
        output[0].audio,
        expected,
    )
