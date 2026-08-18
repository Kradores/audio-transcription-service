from __future__ import annotations

from pathlib import Path

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


def test_audio_capture_settings_accepts_valid_values() -> None:
    settings = SettingsBuilder().build()
    assert settings.audio.capture.queue_capacity == 100


def test_audio_processing_settings_accepts_valid_values() -> None:
    settings = SettingsBuilder().build()
    assert settings.audio.processing.sample_rate == 16_000
    assert settings.audio.processing.channels == 1


def test_audio_segmentation_settings_accepts_valid_values() -> None:
    settings = SettingsBuilder().build()
    assert settings.audio.segmentation.pre_roll_ms == 200
    assert settings.audio.segmentation.post_roll_ms == 200
    assert settings.audio.segmentation.target_duration_seconds == 3
    assert settings.audio.segmentation.max_duration_seconds == 5


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


def test_transcription_settings_accepts_valid_values() -> None:
    settings = SettingsBuilder().build()
    assert settings.transcription.queue_capacity == 10


def test_database_settings_accepts_valid_values() -> None:
    settings = SettingsBuilder().build()
    assert settings.database.path == Path("data/transcripts.db")


def test_settings_accepts_valid_values() -> None:
    settings = SettingsBuilder().build()
    assert settings.application.name == "Audio Transcription Service"
    assert settings.api.port == 8080
    assert settings.audio.processing.sample_rate == 16_000
    assert settings.vad.speech_threshold == 0.5
    assert settings.whisper.model is WhisperModel.SMALL
    assert settings.database.path == Path("data/transcripts.db")


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
    "queue_capacity",
    [
        1,
        10_000,
    ],
)
def test_audio_capture_settings_accepts_boundary_values(queue_capacity: int) -> None:
    settings = SettingsBuilder().with_capture_queue_capacity(queue_capacity).build()
    assert settings.audio.capture.queue_capacity == queue_capacity


@pytest.mark.parametrize(
    "sample_rate, channels",
    [
        (8_000, 1),
        (8_000, 2),
        (192_000, 1),
        (192_000, 2),
    ],
)
def test_audio_processing_settings_accepts_boundary_values(sample_rate: int, channels: int) -> None:
    settings = SettingsBuilder().with_sample_rate(sample_rate).with_channels(channels).build()
    assert settings.audio.processing.sample_rate == sample_rate
    assert settings.audio.processing.channels == channels


@pytest.mark.parametrize(
    "pre_roll_ms, post_roll_ms, target_duration_seconds, max_duration_seconds",
    [
        (0, 0, 1, 2),
        (1000, 1000, 10, 20),
    ],
)
def test_audio_segmentation_settings_accepts_boundary_values(
    pre_roll_ms: int,
    post_roll_ms: int,
    target_duration_seconds: int,
    max_duration_seconds: int,
) -> None:
    settings = (
        SettingsBuilder()
        .with_pre_roll_ms(pre_roll_ms)
        .with_post_roll_ms(post_roll_ms)
        .with_target_duration_seconds(target_duration_seconds)
        .with_max_duration_seconds(max_duration_seconds)
        .build()
    )
    assert settings.audio.segmentation.pre_roll_ms == pre_roll_ms
    assert settings.audio.segmentation.post_roll_ms == post_roll_ms
    assert settings.audio.segmentation.target_duration_seconds == target_duration_seconds
    assert settings.audio.segmentation.max_duration_seconds == max_duration_seconds


@pytest.mark.parametrize(
    "queue_capacity",
    [
        0,
        10_001,
    ],
)
def test_audio_capture_settings_rejects_invalid_values(queue_capacity: int) -> None:
    with pytest.raises(ValidationError):
        SettingsBuilder().with_capture_queue_capacity(queue_capacity).build()


@pytest.mark.parametrize(
    "queue_capacity",
    [
        0,
        10_001,
    ],
)
def test_transcription_settings_rejects_invalid_values(queue_capacity: int) -> None:
    with pytest.raises(ValidationError):
        SettingsBuilder().with_transcription_queue_capacity(queue_capacity).build()


@pytest.mark.parametrize(
    "sample_rate, channels",
    [
        (7_900, 1),
        (8_000, 0),
        (193_000, 2),
        (192_000, 3),
    ],
)
def test_audio_processing_settings_rejects_invalid_values(sample_rate: int, channels: int) -> None:
    with pytest.raises(ValidationError):
        (SettingsBuilder().with_sample_rate(sample_rate).with_channels(channels).build())


@pytest.mark.parametrize(
    "pre_roll_ms, post_roll_ms, target_duration_seconds, max_duration_seconds",
    [
        (-1, 0, 1, 2),
        (0, -1, 1, 2),
        (0, 0, 0, 2),
        (0, 0, 1, 0),
    ],
)
def test_audio_segmentation_settings_rejects_invalid_values(
    pre_roll_ms: int,
    post_roll_ms: int,
    target_duration_seconds: int,
    max_duration_seconds: int,
) -> None:
    with pytest.raises(ValidationError):
        (
            SettingsBuilder()
            .with_pre_roll_ms(pre_roll_ms)
            .with_post_roll_ms(post_roll_ms)
            .with_target_duration_seconds(target_duration_seconds)
            .with_max_duration_seconds(max_duration_seconds)
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
