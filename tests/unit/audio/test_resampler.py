import numpy as np

from app.audio.resampler import IdentityAudioResampler, SoXRResampler


def test_resampler_preserves_sample_count_at_same_sample_rate() -> None:
    # Arrange
    resampler = SoXRResampler(
        input_sample_rate=16_000,
        output_sample_rate=16_000,
        channels=1,
    )
    audio = np.zeros((320, 1), dtype=np.float32)

    # Act
    output = resampler.process(audio)

    # Assert
    assert output.shape == (320, 1)
    assert output.dtype == np.float32


def test_resampler_downsamples_audio_after_flush() -> None:
    # Arrange
    resampler = SoXRResampler(
        input_sample_rate=48_000,
        output_sample_rate=16_000,
        channels=1,
    )
    audio = np.zeros((480, 1), dtype=np.float32)

    # Act
    output = resampler.process(audio)
    flushed = resampler.flush()

    # Assert
    combined = np.concatenate(
        (output, flushed),
        axis=0,
    )

    assert combined.shape == (160, 1)
    assert combined.dtype == np.float32


def test_resampler_upsamples_audio_after_flush() -> None:
    # Arrange
    resampler = SoXRResampler(
        input_sample_rate=16_000,
        output_sample_rate=48_000,
        channels=1,
    )
    audio = np.zeros((160, 1), dtype=np.float32)

    # Act
    output = resampler.process(audio)
    flushed = resampler.flush()

    # Assert
    combined = np.concatenate(
        (output, flushed),
        axis=0,
    )

    assert combined.shape == (480, 1)
    assert combined.dtype == np.float32


def test_resampler_preserves_channels() -> None:
    # Arrange
    resampler = SoXRResampler(
        input_sample_rate=48_000,
        output_sample_rate=16_000,
        channels=2,
    )
    audio = np.zeros((480, 2), dtype=np.float32)

    # Act
    output = resampler.process(audio)

    # Assert
    assert output.shape[1] == 2
    assert output.dtype == np.float32


def test_resampler_processes_stream_continuously() -> None:
    # Arrange
    resampler = SoXRResampler(
        input_sample_rate=48_000,
        output_sample_rate=16_000,
        channels=1,
    )
    first = np.ones((480, 1), dtype=np.float32)
    second = np.full((480, 1), 2.0, dtype=np.float32)

    # Act
    first_output = resampler.process(first)
    second_output = resampler.process(second)
    flushed = resampler.flush()

    output = np.concatenate(
        (
            first_output,
            second_output,
            flushed,
        ),
        axis=0,
    )

    # Assert
    assert output.shape == (320, 1)
    assert output.shape[1] == 1
    assert output.dtype == np.float32


def test_resampler_flush_returns_remaining_output() -> None:
    # Arrange
    resampler = SoXRResampler(
        input_sample_rate=48_000,
        output_sample_rate=16_000,
        channels=1,
    )
    audio = np.zeros((481, 1), dtype=np.float32)

    # Act
    output = resampler.process(audio)
    flushed = resampler.flush()

    # Assert
    combined = np.concatenate(
        (output, flushed),
        axis=0,
    )

    assert combined.shape == (160, 1)
    assert combined.shape[1] == 1
    assert combined.dtype == np.float32


def test_resampler_may_buffer_initial_input() -> None:
    # Arrange
    resampler = SoXRResampler(
        input_sample_rate=48_000,
        output_sample_rate=16_000,
        channels=1,
    )
    audio = np.zeros((480, 1), dtype=np.float32)

    # Act
    output = resampler.process(audio)

    # Assert
    assert output.shape == (0, 1)


def test_identity_resampler_preserves_audio() -> None:
    # Arrange
    resampler = IdentityAudioResampler(channels=1)
    audio = np.arange(320, dtype=np.float32).reshape(320, 1)

    # Act
    output = resampler.process(audio)

    # Assert
    np.testing.assert_array_equal(output, audio)
    assert output.dtype == np.float32


def test_identity_resampler_preserves_stereo_audio() -> None:
    # Arrange
    resampler = IdentityAudioResampler(channels=2)
    audio = np.arange(640, dtype=np.float32).reshape(320, 2)

    # Act
    output = resampler.process(audio)

    # Assert
    np.testing.assert_array_equal(output, audio)
    assert output.shape == (320, 2)


def test_identity_resampler_flush_returns_empty_audio() -> None:
    # Arrange
    resampler = IdentityAudioResampler(channels=1)

    # Act
    output = resampler.flush()

    # Assert
    assert output.shape == (0, 1)
    assert output.dtype == np.float32


def test_identity_resampler_preserves_streaming_chunks() -> None:
    # Arrange
    resampler = IdentityAudioResampler(channels=1)
    first = np.ones((100, 1), dtype=np.float32)
    second = np.full((100, 1), 2.0, dtype=np.float32)

    # Act
    first_output = resampler.process(first)
    second_output = resampler.process(second)

    # Assert
    np.testing.assert_array_equal(first_output, first)
    np.testing.assert_array_equal(second_output, second)
