import wave
from pathlib import Path

import numpy as np
import pytest

from app.audio.contracts import AudioFormat, AudioFrame, ProcessingAudioFrame, SpeechSegment
from app.audio.normalizer import AudioNormalizerImpl
from app.audio.resampler import SoXRResamplerFactory
from app.composition import (
    create_transcriber,
    create_whisper_model,
    resolve_configured_whisper_model_path,
)
from app.core.config.loader import ConfigurationLoader
from app.core.runtime_paths import create_development_runtime_paths
from tests.integration.constants import INTEGRATION_CONFIGURATION_PATH

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


def _create_speech_segment(
    processing_frames: tuple[ProcessingAudioFrame, ...],
) -> SpeechSegment:
    audio = np.concatenate(
        [processing_frame.audio for processing_frame in processing_frames],
        axis=0,
    )

    timestamp = processing_frames[0].timestamp
    duration = audio.shape[0] / processing_frames[0].format.sample_rate

    return SpeechSegment(
        audio=audio,
        timestamp=timestamp,
        duration=duration,
        format=processing_frames[0].format,
    )


@pytest.mark.slow_integration
@pytest.mark.timeout(120)
def test_real_faster_whisper_transcribes_audio_fixture() -> None:
    # Arrange
    runtime_paths = create_development_runtime_paths(
        config_path=INTEGRATION_CONFIGURATION_PATH,
    )
    settings = ConfigurationLoader(runtime_paths).load()

    model_path = resolve_configured_whisper_model_path(
        runtime_paths,
        settings,
    )

    normalizer = AudioNormalizerImpl(
        settings=settings.audio.processing,
        resampler_factory=SoXRResamplerFactory(),
    )

    frame = _read_wav(FIXTURE_PATH)
    processing_frames = normalizer.process(frame) + normalizer.flush()

    segment = _create_speech_segment(processing_frames)

    model = create_whisper_model(settings, model_path=model_path)
    transcriber = create_transcriber(model)

    # Act
    result = transcriber.transcribe(segment)

    # Assert
    assert result.text.strip()
    assert result.language == "en"

    assert result.start == segment.timestamp
    assert result.end == segment.timestamp + segment.duration
