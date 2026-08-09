import numpy as np
import pytest

from app.audio.contracts import (
    AudioFormat,
    AudioFrame,
    AudioSampleType,
    ProcessingAudioFrame,
    SpeechEnd,
    SpeechSegment,
    SpeechStart,
)


def test_audio_format_accepts_valid_values() -> None:
    audio_format = AudioFormat(
        sample_rate=48_000,
        channels=2,
        sample_type="int16",
    )

    assert audio_format.sample_rate == 48_000
    assert audio_format.channels == 2
    assert audio_format.sample_type == "int16"


@pytest.mark.parametrize(
    ("sample_rate", "channels", "sample_type"),
    [
        (0, 1, "int16"),
        (48_000, 0, "int16"),
        (48_000, 3, "int16"),
        (48_000, 2, "int64"),
    ],
)
def test_audio_format_rejects_invalid_values(
    sample_rate: int,
    channels: int,
    sample_type: AudioSampleType,
) -> None:
    with pytest.raises(ValueError):
        AudioFormat(
            sample_rate=sample_rate,
            channels=channels,
            sample_type=sample_type,
        )


def test_audio_frame_requires_matching_channel_count() -> None:
    audio_format = AudioFormat(
        sample_rate=48_000,
        channels=2,
        sample_type="int16",
    )

    audio = np.zeros((480, 1), dtype=np.int16)

    with pytest.raises(ValueError):
        AudioFrame(
            audio=audio,
            timestamp=1.0,
            format=audio_format,
        )


def test_processing_audio_frame_requires_exactly_20_ms() -> None:
    audio = np.zeros((320, 1), dtype=np.float32)

    frame = ProcessingAudioFrame(
        audio=audio,
        timestamp=1.0,
    )

    assert frame.audio.shape == (320, 1)


@pytest.mark.parametrize("samples", [319, 321, 640])
def test_processing_audio_frame_rejects_wrong_frame_size(samples: int) -> None:
    audio = np.zeros((samples, 1), dtype=np.float32)

    with pytest.raises(ValueError):
        ProcessingAudioFrame(
            audio=audio,
            timestamp=1.0,
        )


def test_processing_audio_frame_requires_mono_audio() -> None:
    audio = np.zeros((320, 2), dtype=np.float32)

    with pytest.raises(ValueError):
        ProcessingAudioFrame(
            audio=audio,
            timestamp=1.0,
        )


@pytest.mark.parametrize("event_type", [SpeechStart, SpeechEnd])
def test_speech_event_rejects_negative_timestamp(event_type: type) -> None:
    with pytest.raises(ValueError):
        event_type(timestamp=-1.0)


def test_speech_segment_duration_matches_audio() -> None:
    audio = np.zeros((16_000, 1), dtype=np.float32)

    segment = SpeechSegment(
        audio=audio,
        timestamp=10.0,
        duration=1.0,
        format=AudioFormat(
            sample_rate=16_000,
            channels=1,
            sample_type="float32",
        ),
    )

    assert segment.duration == 1.0


def test_speech_segment_rejects_incorrect_duration() -> None:
    audio = np.zeros((16_000, 1), dtype=np.float32)

    with pytest.raises(ValueError):
        SpeechSegment(
            audio=audio,
            timestamp=10.0,
            duration=2.0,
            format=AudioFormat(
                sample_rate=16_000,
                channels=1,
                sample_type="float32",
            ),
        )


def test_speech_segment_requires_16_khz_mono_audio() -> None:
    audio = np.zeros((16_000, 1), dtype=np.float32)

    with pytest.raises(ValueError):
        SpeechSegment(
            audio=audio,
            timestamp=10.0,
            duration=1.0,
            format=AudioFormat(
                sample_rate=48_000,
                channels=1,
                sample_type="float32",
            ),
        )
