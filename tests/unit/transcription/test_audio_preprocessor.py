from __future__ import annotations

import logging

import numpy as np
import pytest

from app.audio.contracts import (
    AudioFormat,
    SpeechSegment,
)
from app.transcription.audio_preprocessor import (
    FixedGainTranscriptionAudioPreprocessor,
    IdentityTranscriptionAudioPreprocessor,
)
from app.transcription.contracts import AudioSource

AUDIO_FORMAT = AudioFormat(
    sample_rate=16_000,
    channels=1,
    sample_type="float32",
)


def create_segment(
    audio: np.ndarray,
) -> SpeechSegment:
    return SpeechSegment(
        audio=audio,
        timestamp=3.5,
        duration=audio.shape[0] / 16_000,
        format=AUDIO_FORMAT,
    )


def test_identity_preprocessor_returns_same_segment() -> None:
    segment = create_segment(
        np.array(
            [[0.1], [-0.2]],
            dtype=np.float32,
        )
    )

    processor = IdentityTranscriptionAudioPreprocessor()

    result = processor.process(segment)

    assert result is segment


def test_zero_db_preserves_audio_values() -> None:
    segment = create_segment(
        np.array(
            [[0.1], [-0.2], [0.3]],
            dtype=np.float32,
        )
    )

    processor = FixedGainTranscriptionAudioPreprocessor(
        gain_db=0.0,
        source=AudioSource.MICROPHONE,
    )

    result = processor.process(segment)

    np.testing.assert_array_equal(
        result.audio,
        segment.audio,
    )


def test_positive_gain_amplifies_audio() -> None:
    segment = create_segment(
        np.array(
            [[0.1], [-0.2]],
            dtype=np.float32,
        )
    )

    processor = FixedGainTranscriptionAudioPreprocessor(
        gain_db=6.0,
        source=AudioSource.MICROPHONE,
    )

    result = processor.process(segment)

    expected_gain = 10 ** (6.0 / 20.0)

    np.testing.assert_allclose(
        result.audio,
        segment.audio * expected_gain,
        rtol=1e-6,
    )


def test_negative_gain_attenuates_audio() -> None:
    segment = create_segment(
        np.array(
            [[0.4], [-0.8]],
            dtype=np.float32,
        )
    )

    processor = FixedGainTranscriptionAudioPreprocessor(
        gain_db=-6.0,
        source=AudioSource.MICROPHONE,
    )

    result = processor.process(segment)

    expected_gain = 10 ** (-6.0 / 20.0)

    np.testing.assert_allclose(
        result.audio,
        segment.audio * expected_gain,
        rtol=1e-6,
    )


def test_gain_clips_audio_to_valid_float_range() -> None:
    segment = create_segment(
        np.array(
            [[0.5], [-0.5]],
            dtype=np.float32,
        )
    )

    processor = FixedGainTranscriptionAudioPreprocessor(
        gain_db=12.0,
        source=AudioSource.MICROPHONE,
    )

    result = processor.process(segment)

    np.testing.assert_array_equal(
        result.audio,
        np.array(
            [[1.0], [-1.0]],
            dtype=np.float32,
        ),
    )


def test_gain_preserves_segment_metadata() -> None:
    segment = create_segment(
        np.array(
            [[0.1], [0.2]],
            dtype=np.float32,
        )
    )

    processor = FixedGainTranscriptionAudioPreprocessor(
        gain_db=6.0,
        source=AudioSource.MICROPHONE,
    )

    result = processor.process(segment)

    assert result.timestamp == segment.timestamp
    assert result.duration == segment.duration
    assert result.format == segment.format


def test_gain_does_not_mutate_input_audio() -> None:
    audio = np.array(
        [[0.1], [-0.2]],
        dtype=np.float32,
    )
    original = audio.copy()

    segment = create_segment(audio)

    processor = FixedGainTranscriptionAudioPreprocessor(
        gain_db=12.0,
        source=AudioSource.MICROPHONE,
    )

    processor.process(segment)

    np.testing.assert_array_equal(
        segment.audio,
        original,
    )


def test_gain_returns_float32_contiguous_audio() -> None:
    segment = create_segment(
        np.array(
            [[0.1], [-0.2]],
            dtype=np.float32,
        )
    )

    processor = FixedGainTranscriptionAudioPreprocessor(
        gain_db=6.0,
        source=AudioSource.MICROPHONE,
    )

    result = processor.process(segment)

    assert result.audio.dtype == np.float32
    assert result.audio.flags.c_contiguous


def test_clipping_logs_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    segment = create_segment(
        np.array(
            [[0.5], [-0.5]],
            dtype=np.float32,
        )
    )

    processor = FixedGainTranscriptionAudioPreprocessor(
        gain_db=12.0,
        source=AudioSource.MICROPHONE,
    )

    with caplog.at_level(logging.WARNING):
        processor.process(segment)

    assert "transcription audio clipped" in caplog.text
    assert "gain_db=12.0" in caplog.text
    assert "clipped_samples=2" in caplog.text
    assert "source=microphone" in caplog.text
