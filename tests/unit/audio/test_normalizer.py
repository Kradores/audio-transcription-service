import numpy as np
import pytest

from app.audio.contracts import AudioFormat, AudioFrame, Float32Audio, Int16Audio
from app.audio.normalizer import AudioNormalizerImpl
from app.audio.resampler import IdentityAudioResampler, SoXRResamplerFactory
from app.core.config.models import AudioProcessingSettings


class FakeAudioResampler:
    def __init__(
        self,
        outputs: list[Float32Audio],
        flush_output: Float32Audio | None = None,
    ) -> None:
        self._outputs = outputs
        self._flush_output = (
            flush_output if flush_output is not None else np.empty((0, 1), dtype=np.float32)
        )
        self.processed: list[Float32Audio] = []
        self.flush_called = False
        self.reset_called = False

    def process(self, audio: Float32Audio) -> Float32Audio:
        self.processed.append(audio)

        if self._outputs:
            return self._outputs.pop(0)

        return np.empty(
            (0, audio.shape[1]),
            dtype=np.float32,
        )

    def flush(self) -> Float32Audio:
        self.flush_called = True
        return self._flush_output

    def reset(self) -> None:
        self.reset_called = True


class FakeAudioResamplerFactory:
    def __init__(
        self,
        resampler: FakeAudioResampler,
    ) -> None:
        self._resampler = resampler

    def create(
        self,
        input_sample_rate: int,
        output_sample_rate: int,
        channels: int,
    ) -> FakeAudioResampler:
        return self._resampler


class IdentityAudioResamplerFactory:
    def create(
        self,
        input_sample_rate: int,
        output_sample_rate: int,
        channels: int,
    ) -> IdentityAudioResampler:
        return IdentityAudioResampler(channels)


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
    audio: Int16Audio,
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


def create_normalizer(
    settings: AudioProcessingSettings | None = None,
) -> AudioNormalizerImpl:
    if settings is None:
        settings = create_settings()

    return AudioNormalizerImpl(
        settings,
        IdentityAudioResamplerFactory(),
    )


def test_normalizer_emits_one_processing_frame_for_20_ms_input() -> None:
    # Arrange
    normalizer = create_normalizer()
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
    normalizer = create_normalizer()
    audio = np.ones((160, 1), dtype=np.int16)
    frame = create_frame(audio)

    # Act
    output = normalizer.process(frame)

    # Assert
    assert output == ()


def test_normalizer_combines_partial_input_frames() -> None:
    # Arrange
    normalizer = create_normalizer()

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
    normalizer = create_normalizer()
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
    normalizer = create_normalizer()
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
    normalizer = create_normalizer()
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
    normalizer = create_normalizer()
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


def test_normalizer_downmixes_stereo_to_mono() -> None:
    # Arrange
    normalizer = create_normalizer()
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
    normalizer = create_normalizer()

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
    normalizer = create_normalizer()

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
    normalizer = create_normalizer(settings)

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
    normalizer = create_normalizer(
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
    normalizer = create_normalizer(
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


def test_normalizer_frames_resampler_output() -> None:
    # Arrange
    settings = create_settings()

    resampled = np.ones(
        (320, 1),
        dtype=np.float32,
    )

    resampler = FakeAudioResampler(
        outputs=[resampled],
    )

    reseampler_factory = FakeAudioResamplerFactory(
        resampler=resampler,
    )

    normalizer = AudioNormalizerImpl(
        settings,
        reseampler_factory,
    )

    frame = create_frame(
        np.zeros((480, 1), dtype=np.int16),
    )

    # Act
    output = normalizer.process(frame)

    # Assert
    assert len(output) == 1
    np.testing.assert_array_equal(
        output[0].audio,
        resampled,
    )


def test_normalizer_handles_empty_resampler_output() -> None:
    # Arrange
    settings = create_settings()

    resampler = FakeAudioResampler(
        outputs=[
            np.empty((0, 1), dtype=np.float32),
            np.ones((320, 1), dtype=np.float32),
        ],
    )

    reseampler_factory = FakeAudioResamplerFactory(
        resampler=resampler,
    )

    normalizer = AudioNormalizerImpl(
        settings,
        reseampler_factory,
    )

    first = create_frame(
        np.zeros((320, 1), dtype=np.int16),
    )
    second = create_frame(
        np.zeros((320, 1), dtype=np.int16),
    )

    # Act
    first_output = normalizer.process(first)
    second_output = normalizer.process(second)

    # Assert
    assert first_output == ()
    assert len(second_output) == 1

    np.testing.assert_array_equal(
        second_output[0].audio,
        np.ones((320, 1), dtype=np.float32),
    )


def test_normalizer_flush_emits_complete_frame_from_resampler() -> None:
    # Arrange
    settings = create_settings()

    resampler = FakeAudioResampler(
        outputs=[
            np.zeros((200, 1), dtype=np.float32),
        ],
        flush_output=np.ones(
            (120, 1),
            dtype=np.float32,
        ),
    )

    reseampler_factory = FakeAudioResamplerFactory(
        resampler=resampler,
    )

    normalizer = AudioNormalizerImpl(
        settings,
        reseampler_factory,
    )

    normalizer.process(
        create_frame(
            np.zeros((320, 1), dtype=np.int16),
        ),
    )

    # Act
    output = normalizer.flush()

    # Assert
    assert len(output) == 1
    assert resampler.flush_called

    np.testing.assert_array_equal(
        output[0].audio[:200],
        np.zeros((200, 1), dtype=np.float32),
    )

    np.testing.assert_array_equal(
        output[0].audio[200:],
        np.ones((120, 1), dtype=np.float32),
    )


def test_normalizer_flush_discards_incomplete_frame() -> None:
    # Arrange
    settings = create_settings()
    resempler_factory = FakeAudioResamplerFactory(
        resampler=FakeAudioResampler(
            outputs=[
                np.zeros((200, 1), dtype=np.float32),
            ],
            flush_output=np.ones(
                (50, 1),
                dtype=np.float32,
            ),
        )
    )

    normalizer = AudioNormalizerImpl(
        settings,
        resempler_factory,
    )

    normalizer.process(
        create_frame(
            np.zeros((320, 1), dtype=np.int16),
        ),
    )

    # Act
    output = normalizer.flush()

    # Assert
    assert output == ()


def test_normalizer_resamples_48_khz_to_16_khz() -> None:
    # Arrange
    settings = create_settings(sample_rate=16_000)
    normalizer = AudioNormalizerImpl(
        settings,
        SoXRResamplerFactory(),
    )

    audio = np.zeros((960, 1), dtype=np.int16)

    frame = AudioFrame(
        audio=audio,
        timestamp=10.0,
        format=AudioFormat(
            sample_rate=48_000,
            channels=1,
            sample_type="int16",
        ),
    )

    # Act
    first_output = normalizer.process(frame)
    final_output = normalizer.flush()

    output = first_output + final_output

    # Assert
    assert all(frame.audio.shape == (320, 1) for frame in output)
    assert output[0].audio.dtype == np.float32
    assert output[0].timestamp == pytest.approx(10.0)


def test_normalizer_resamples_continuous_stream() -> None:
    # Arrange
    settings = create_settings(sample_rate=16_000)
    normalizer = AudioNormalizerImpl(
        settings,
        SoXRResamplerFactory(),
    )

    first = AudioFrame(
        audio=np.zeros((480, 1), dtype=np.int16),
        timestamp=20.0,
        format=AudioFormat(
            sample_rate=48_000,
            channels=1,
            sample_type="int16",
        ),
    )
    second = AudioFrame(
        audio=np.zeros((480, 1), dtype=np.int16),
        timestamp=20.01,
        format=AudioFormat(
            sample_rate=48_000,
            channels=1,
            sample_type="int16",
        ),
    )

    # Act
    first_output = normalizer.process(first)
    second_output = normalizer.process(second)
    final_output = normalizer.flush()

    output = first_output + second_output + final_output

    # Assert
    assert sum(frame.audio.shape[0] for frame in output) == 320
    assert output[0].audio.shape == (320, 1)
    assert output[0].timestamp == pytest.approx(20.0)


def test_normalizer_accepts_input_sample_rate_different_from_processing_rate() -> None:
    # Arrange
    settings = create_settings(sample_rate=16_000)
    normalizer = AudioNormalizerImpl(
        settings,
        SoXRResamplerFactory(),
    )

    frame = AudioFrame(
        audio=np.zeros((960, 1), dtype=np.int16),
        timestamp=0.0,
        format=AudioFormat(
            sample_rate=48_000,
            channels=1,
            sample_type="int16",
        ),
    )

    # Act
    output = normalizer.process(frame)
    output += normalizer.flush()

    # Assert
    assert all(frame.audio.shape == (320, 1) for frame in output)
    assert output[0].format.sample_rate == 16_000


def test_normalizer_resamples_48_khz_stream_into_processing_frames() -> None:
    # Arrange
    settings = create_settings(sample_rate=16_000)
    normalizer = AudioNormalizerImpl(
        settings,
        SoXRResamplerFactory(),
    )

    first = AudioFrame(
        audio=np.zeros((960, 1), dtype=np.int16),
        timestamp=10.0,
        format=AudioFormat(
            sample_rate=48_000,
            channels=1,
            sample_type="int16",
        ),
    )

    # Act
    output = list(normalizer.process(first))
    output.extend(normalizer.flush())

    # Assert
    assert output
    assert all(frame.audio.shape == (320, 1) for frame in output)
    assert sum(frame.audio.shape[0] for frame in output) == 320
    assert output[0].timestamp == pytest.approx(10.0)
    assert output[0].format.sample_rate == 16_000


def test_normalizer_reset_discards_buffered_audio() -> None:
    normalizer = create_normalizer()

    first = create_frame(
        np.ones((160, 1), dtype=np.int16),
    )

    assert normalizer.process(first) == ()

    normalizer.reset()

    second = create_frame(
        np.full((160, 1), 2, dtype=np.int16),
    )

    output = normalizer.process(second)

    assert output == ()


def test_normalizer_reset_starts_new_processing_continuity() -> None:
    normalizer = create_normalizer()

    normalizer.process(
        create_frame(
            np.ones((160, 1), dtype=np.int16),
        ),
    )

    normalizer.reset()

    output = normalizer.process(
        create_frame(
            np.full((320, 1), 2, dtype=np.int16),
        ),
    )

    assert len(output) == 1

    np.testing.assert_array_equal(
        output[0].audio[:, 0],
        np.full(
            320,
            2 / 32768.0,
            dtype=np.float32,
        ),
    )


def test_normalizer_reset_resets_resampler() -> None:
    settings = create_settings()

    resampler = FakeAudioResampler(
        outputs=[
            np.empty((0, 1), dtype=np.float32),
        ],
    )

    factory = FakeAudioResamplerFactory(resampler)

    normalizer = AudioNormalizerImpl(
        settings,
        factory,
    )

    normalizer.process(
        create_frame(
            np.zeros((320, 1), dtype=np.int16),
        ),
    )

    normalizer.reset()
    assert resampler.reset_called


def test_normalizer_reset_does_not_flush_resampler() -> None:
    # Arrange
    settings = create_settings()

    resampler = FakeAudioResampler(
        outputs=[
            np.empty((0, 1), dtype=np.float32),
        ],
        flush_output=np.ones(
            (320, 1),
            dtype=np.float32,
        ),
    )

    normalizer = AudioNormalizerImpl(
        settings,
        FakeAudioResamplerFactory(resampler),
    )

    normalizer.process(
        create_frame(
            np.zeros((320, 1), dtype=np.int16),
        ),
    )

    # Act
    normalizer.reset()

    # Assert
    assert resampler.reset_called
    assert not resampler.flush_called
