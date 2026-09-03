from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.core.config.enums import (
    ApplicationEnvironment,
    LogLevel,
    TranscriptionLanguageMode,
    WhisperComputeType,
    WhisperDevice,
    WhisperModel,
    WhisperRuntime,
)


class BaseConfigurationModel(BaseModel):
    """Base class for all configuration models."""

    model_config = ConfigDict(frozen=True, extra="forbid", validate_assignment=False)


class ApplicationSettings(BaseConfigurationModel):
    """Application configuration."""

    name: str
    environment: ApplicationEnvironment

    @property
    def is_development(self) -> bool:
        return self.environment == ApplicationEnvironment.DEVELOPMENT

    @property
    def is_production(self) -> bool:
        return self.environment == ApplicationEnvironment.PRODUCTION

    @property
    def is_test(self) -> bool:
        return self.environment == ApplicationEnvironment.TEST


class ApiSettings(BaseConfigurationModel):
    """Configuration settings for the API server connection."""

    host: str
    port: Annotated[int, Field(ge=1, le=65535)]


class FileLoggingSettings(BaseConfigurationModel):
    """Configuration for persistent application log output."""

    enabled: bool
    path: Path
    max_bytes: Annotated[int, Field(gt=0)]
    backup_count: Annotated[int, Field(ge=0)]


class LoggingSettings(BaseConfigurationModel):
    """Configuration settings for application logging outputs."""

    level: LogLevel
    file: FileLoggingSettings


class AudioCaptureSettings(BaseConfigurationModel):
    """Configuration for audio capture."""

    queue_capacity: Annotated[int, Field(ge=1, le=10_000)]


class AudioProcessingSettings(BaseConfigurationModel):
    sample_rate: Annotated[int, Field(ge=8_000, le=192_000)]
    channels: Annotated[int, Field(ge=1, le=2)]


class AudioSegmentationSettings(BaseConfigurationModel):
    pre_roll_ms: Annotated[int, Field(ge=0)]
    post_roll_ms: Annotated[int, Field(ge=0)]
    target_duration_seconds: Annotated[int, Field(ge=1, le=30)]
    max_duration_seconds: Annotated[int, Field(ge=1, le=30)]


class AudioSettings(BaseConfigurationModel):
    capture: AudioCaptureSettings
    processing: AudioProcessingSettings
    segmentation: AudioSegmentationSettings


class VadSettings(BaseConfigurationModel):
    """Configuration parameters for Voice Activity Detection (VAD)."""

    enabled: bool
    speech_threshold: Annotated[float, Field(ge=0.0, le=1.0)]
    min_silence_duration_ms: Annotated[int, Field(ge=0)]


class WhisperSettings(BaseConfigurationModel):
    """Configuration options for the OpenAI Whisper speech-to-text model."""

    model: WhisperModel
    runtime: WhisperRuntime
    device: WhisperDevice
    compute_type: WhisperComputeType


class DatabaseSettings(BaseConfigurationModel):
    """Configuration settings for the local file-based database path."""

    path: Path


type LanguageCode = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        to_lower=True,
        min_length=1,
    ),
]


class AutoTranscriptionLanguageSettings(BaseConfigurationModel):
    """Detect language independently for each transcription work item."""

    mode: Literal[TranscriptionLanguageMode.AUTO]


class FixedTranscriptionLanguageSettings(BaseConfigurationModel):
    """Decode every transcription work item using one configured language."""

    mode: Literal[TranscriptionLanguageMode.FIXED]
    language: LanguageCode


class AdaptiveTranscriptionLanguageSettings(BaseConfigurationModel):
    """Maintain conversation language state while allowing language switches."""

    mode: Literal[TranscriptionLanguageMode.ADAPTIVE]
    initial_language: LanguageCode | None
    min_probe_duration_seconds: Annotated[float, Field(gt=0.0)]
    switch_probability_threshold: Annotated[float, Field(gt=0.0, le=1.0)]
    switch_confirmations: Annotated[int, Field(ge=1)]


type TranscriptionLanguageSettings = Annotated[
    AutoTranscriptionLanguageSettings
    | FixedTranscriptionLanguageSettings
    | AdaptiveTranscriptionLanguageSettings,
    Field(discriminator="mode"),
]


class TranscriptionAggregationSettings(BaseConfigurationModel):
    """Configuration for speech-segment aggregation before transcription."""

    enabled: bool
    target_duration_seconds: Annotated[float, Field(gt=0.0)]
    max_duration_seconds: Annotated[float, Field(gt=0.0)]
    max_gap_seconds: Annotated[float, Field(ge=0.0)]
    max_wait_seconds: Annotated[float, Field(ge=0.0)]

    @model_validator(mode="after")
    def validate_target_does_not_exceed_maximum(self) -> Self:
        if self.target_duration_seconds > self.max_duration_seconds:
            raise ValueError("target_duration_seconds must not exceed max_duration_seconds")

        return self


class TranscriptionSettings(BaseConfigurationModel):
    """Configuration for asynchronous transcription execution."""

    queue_capacity: Annotated[int, Field(ge=1, le=10_000)]
    worker_count: Annotated[int, Field(ge=1)]
    language: TranscriptionLanguageSettings
    aggregation: TranscriptionAggregationSettings


class Settings(BaseConfigurationModel):
    """Root configuration object containing all sub-system application settings."""

    application: ApplicationSettings
    api: ApiSettings
    logging: LoggingSettings
    audio: AudioSettings
    transcription: TranscriptionSettings
    vad: VadSettings
    whisper: WhisperSettings
    database: DatabaseSettings


__all__ = [
    "ApplicationSettings",
    "ApiSettings",
    "AudioSettings",
    "BaseConfigurationModel",
    "DatabaseSettings",
    "FileLoggingSettings",
    "LoggingSettings",
    "Settings",
    "VadSettings",
    "WhisperSettings",
    "AdaptiveTranscriptionLanguageSettings",
    "AutoTranscriptionLanguageSettings",
    "FixedTranscriptionLanguageSettings",
    "LanguageCode",
    "TranscriptionAggregationSettings",
    "TranscriptionLanguageSettings",
    "TranscriptionSettings",
]
