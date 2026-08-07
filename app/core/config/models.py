from __future__ import annotations

from pathlib import Path
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from app.core.config.enums import (
    ApplicationEnvironment,
    LogLevel,
    WhisperComputeType,
    WhisperDevice,
    WhisperModel,
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


class LoggingSettings(BaseConfigurationModel):
    """Configuration settings for application logging outputs."""

    level: LogLevel


class AudioSettings(BaseConfigurationModel):
    """Configuration for audio capture."""

    sample_rate: Annotated[int, Field(ge=8_000, le=192_000)]
    channels: Annotated[int, Field(ge=1, le=2)]
    chunk_seconds: Annotated[int, Field(ge=1, le=30)]


class VadSettings(BaseConfigurationModel):
    """Configuration parameters for Voice Activity Detection (VAD)."""

    enabled: bool
    speech_threshold: Annotated[float, Field(ge=0.0, le=1.0)]
    min_silence_duration_ms: Annotated[int, Field(ge=0)]


class WhisperSettings(BaseConfigurationModel):
    """Configuration options for the OpenAI Whisper speech-to-text model."""

    model: WhisperModel
    device: WhisperDevice
    compute_type: WhisperComputeType


class DatabaseSettings(BaseConfigurationModel):
    """Configuration settings for the local file-based database path."""

    path: Path


class Settings(BaseConfigurationModel):
    """Root configuration object containing all sub-system application settings."""

    application: ApplicationSettings
    api: ApiSettings
    logging: LoggingSettings
    audio: AudioSettings
    vad: VadSettings
    whisper: WhisperSettings
    database: DatabaseSettings


__all__ = [
    "ApplicationSettings",
    "ApiSettings",
    "AudioSettings",
    "BaseConfigurationModel",
    "DatabaseSettings",
    "LoggingSettings",
    "Settings",
    "VadSettings",
    "WhisperSettings",
]
