from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config.enums import (
    ApplicationEnvironment,
    LogLevel,
    WhisperComputeType,
    WhisperDevice,
    WhisperModel,
)
from app.core.config.models import (
    ApiSettings,
    ApplicationSettings,
    Settings,
)

from .builders import SettingsBuilder


def test_application_settings_accepts_valid_values() -> None:
    settings = SettingsBuilder().build()
    assert settings.application.name == "Audio Transcription Service"
    assert settings.application.environment is ApplicationEnvironment.DEVELOPMENT


def test_api_settings_accepts_valid_values() -> None:
    settings = SettingsBuilder().build()
    assert settings.api.host == "127.0.0.1"
    assert settings.api.port == 8080


def test_logging_settings_accepts_valid_values() -> None:
    settings = SettingsBuilder().build()
    assert settings.logging.level is LogLevel.INFO


def test_audio_settings_accepts_valid_values() -> None:
    settings = SettingsBuilder().build()
    assert settings.audio.sample_rate == 16_000
    assert settings.audio.channels == 1
    assert settings.audio.chunk_seconds == 5


def test_vad_settings_accepts_valid_values() -> None:
    settings = SettingsBuilder().build()
    assert settings.vad.enabled is True
    assert settings.vad.speech_threshold == 0.5
    assert settings.vad.min_silence_duration_ms == 500


def test_whisper_settings_accepts_valid_values() -> None:
    settings = SettingsBuilder().build()
    assert settings.whisper.model is WhisperModel.SMALL
    assert settings.whisper.device is WhisperDevice.CPU
    assert settings.whisper.compute_type is WhisperComputeType.INT8


def test_database_settings_accepts_valid_values() -> None:
    settings = SettingsBuilder().build()
    assert settings.database.path == "data/transcripts.db"


def test_settings_accepts_valid_values() -> None:
    settings = SettingsBuilder().build()
    assert settings.application.name == "Audio Transcription Service"
    assert settings.api.port == 8080
    assert settings.audio.sample_rate == 16_000
    assert settings.vad.speech_threshold == 0.5
    assert settings.whisper.model is WhisperModel.SMALL
    assert settings.database.path == "data/transcripts.db"


@pytest.mark.parametrize(
    "port",
    [
        1,
        65535,
    ],
)
def test_api_settings_accepts_boundary_ports(port: int) -> None:
    settings = SettingsBuilder().with_api_port(port).build()
    assert settings.api.port == port


@pytest.mark.parametrize(
    "port",
    [
        0,
        65536,
    ],
)
def test_api_settings_rejects_invalid_ports(port: int) -> None:
    with pytest.raises(ValidationError):
        SettingsBuilder().with_api_port(port).build()


@pytest.mark.parametrize(
    "sample_rate, channels, chunk_seconds",
    [
        (8_000, 1, 1),
        (8_000, 2, 30),
        (192_000, 1, 30),
        (192_000, 2, 1),
    ]
)
def test_audio_settings_accepts_boundary_values(
    sample_rate: int, channels: int, chunk_seconds: int
) -> None:
    settings = (
        SettingsBuilder()
        .with_sample_rate(sample_rate)
        .with_channels(channels)
        .with_chunk_seconds(chunk_seconds)
        .build()
    )
    assert settings.audio.sample_rate == sample_rate
    assert settings.audio.channels == channels
    assert settings.audio.chunk_seconds == chunk_seconds


@pytest.mark.parametrize(
    "sample_rate, channels, chunk_seconds",
    [
        (7_900, 1, 1),
        (8_000, 0, 1),
        (8_000, 1, 0),
        (193_000, 2, 30),
        (192_000, 3, 30),
        (192_000, 2, 99),
    ]
)
def test_audio_settings_rejects_invalid_values(
    sample_rate: int, channels: int, chunk_seconds: int
) -> None:
    with pytest.raises(ValidationError):
        (
            SettingsBuilder()
            .with_sample_rate(sample_rate)
            .with_channels(channels)
            .with_chunk_seconds(chunk_seconds)
            .build()
        )


@pytest.mark.parametrize(
    "threshold",
    [
        0.0,
        1.0,
    ],
)
def test_vad_settings_accepts_boundary_values(threshold: float) -> None:
    settings = SettingsBuilder().with_speech_threshold(threshold).build()
    assert settings.vad.speech_threshold == threshold


@pytest.mark.parametrize(
    "threshold",
    [
        -0.01,
        1.01,
    ],
)
def test_vad_settings_rejects_invalid_values(threshold: float) -> None:
    with pytest.raises(ValidationError):
        SettingsBuilder().with_speech_threshold(threshold).build()


@pytest.mark.parametrize(
    "environment",
    [
        "development",
        "production",
        "test",
    ],
)
def test_application_settings_accepts_literal_values(environment: str) -> None:
    settings = SettingsBuilder().with_environment(environment).build()
    assert settings.application.environment == environment


@pytest.mark.parametrize(
    "environment",
    [
        "not_a_valid_environment",
        "",
    ],
)
def test_application_settings_rejects_invalid_values(environment: str) -> None:
    with pytest.raises(ValidationError):
        SettingsBuilder().with_environment(environment).build()


def test_settings_are_immutable() -> None:
    settings = SettingsBuilder().build()

    with pytest.raises(ValidationError):
        settings.api = ApiSettings(
            host="localhost",
            port=9000,
        )

    with pytest.raises(ValidationError):
        settings.application.name = "New Name"


def test_application_settings_rejects_extra_fields() -> None:
    document = {
        "name": "App",
        "environment": "development",
        "unexpected": "boom",
    }
    with pytest.raises(ValidationError):
        ApplicationSettings.model_validate(document)


def test_settings_nested_validation() -> None:
    document = SettingsBuilder().with_api_port(70000).build_document()

    with pytest.raises(ValidationError):
        Settings.model_validate(document)
