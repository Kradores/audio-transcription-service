from pathlib import Path

from app.core.config.constants import DEFAULT_CONFIGURATION_PATH
from app.core.config.loader import ConfigurationLoader


def test_default_configuration_loads_successfully() -> None:
    # Arrange
    loader = ConfigurationLoader(DEFAULT_CONFIGURATION_PATH)

    # Act
    settings = loader.load()

    # Assert
    assert settings.application.name == "audio-transcription-service"
    assert settings.application.environment.value == "development"
    assert settings.api.host == "127.0.0.1"
    assert settings.api.port == 8000
    assert settings.audio.processing.sample_rate == 16_000
    assert settings.audio.processing.channels == 1
    assert settings.audio.segmentation.target_duration_seconds == 3
    assert settings.audio.segmentation.max_duration_seconds == 5
    assert settings.vad.enabled is True
    assert settings.vad.speech_threshold == 0.5
    assert settings.vad.min_silence_duration_ms == 300
    assert settings.whisper.model.value == "small"
    assert settings.whisper.device.value == "cpu"
    assert settings.whisper.compute_type.value == "int8"
    assert settings.database.path == (Path("config/transcripts.db").resolve())
