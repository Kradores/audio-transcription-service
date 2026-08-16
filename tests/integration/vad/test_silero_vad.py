import wave
from pathlib import Path

import numpy as np
import pytest

from app.audio.contracts import AudioFormat, AudioFrame, SpeechEnd, SpeechStart
from app.audio.normalizer import AudioNormalizerImpl
from app.audio.resampler import SoXRResamplerFactory
from app.composition import create_vad
from app.core.config.constants import DEFAULT_CONFIGURATION_PATH
from app.core.config.loader import ConfigurationLoader

FIXTURE_PATH = Path(__file__).parents[2] / "fixtures" / "audio" / "english_speech.wav"


def _read_wav(path: Path) -> AudioFrame:
    with wave.open(str(path), "rb") as wav:
        sample_rate = wav.getframerate()
        channels = wav.getnchannels()
        sample_width = wav.getsampwidth()
        frame_count = wav.getnframes()
        audio_bytes = wav.readframes(frame_count)

    assert sample_width == 2

    samples = np.frombuffer(audio_bytes, dtype=np.int16)
    audio = samples.reshape(-1, channels)

    return AudioFrame(
        audio=audio,
        timestamp=0.0,
        format=AudioFormat(
            sample_rate=sample_rate,
            channels=channels,
            sample_type="int16",
        ),
    )


@pytest.mark.slow_integration
@pytest.mark.timeout(120)
def test_real_silero_detects_speech_in_audio_fixture() -> None:
    # Arrange
    settings = ConfigurationLoader(DEFAULT_CONFIGURATION_PATH).load()

    vad = create_vad(settings)
    assert vad is not None

    normalizer = AudioNormalizerImpl(
        settings=settings.audio.processing,
        resampler_factory=SoXRResamplerFactory(),
    )

    frame = _read_wav(FIXTURE_PATH)

    # Act
    processing_frames = normalizer.process(frame) + normalizer.flush()

    events = [
        event for processing_frame in processing_frames for event in vad.process(processing_frame)
    ]

    # Assert
    assert processing_frames

    assert all(
        processing_frame.format.sample_rate == 16_000 for processing_frame in processing_frames
    )
    assert all(processing_frame.format.channels == 1 for processing_frame in processing_frames)
    assert all(
        processing_frame.format.sample_type == "float32" for processing_frame in processing_frames
    )

    starts = [event for event in events if isinstance(event, SpeechStart)]
    ends = [event for event in events if isinstance(event, SpeechEnd)]

    assert starts
    assert ends

    assert starts[0].timestamp < ends[-1].timestamp

    fixture_duration = frame.audio.shape[0] / frame.format.sample_rate

    assert all(0.0 <= event.timestamp <= fixture_duration for event in events)
