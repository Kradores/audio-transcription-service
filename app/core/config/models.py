from __future__ import annotations

from pathlib import Path
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from app.core.config.enums import (
    ApplicationEnvironment,
    LogLevel,
    WhisperComputeType,
    WhisperDevice,
    WhisperModelSize,
)


class BaseSettingsModel(BaseModel):
    """Base class for all configuration models."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
    )


class ApplicationSettings(BaseSettingsModel):
    name: str
    environment: ApplicationEnvironment


class ApiSettings(BaseSettingsModel):
    host: str
    port: Annotated[int, Field(ge=1, le=65535)]


class LoggingSettings(BaseSettingsModel):
    level: LogLevel


class AudioSettings(BaseSettingsModel):
    sample_rate: Annotated[int, Field(ge=8_000, le=192_000)]
    channels: Annotated[int, Field(ge=1, le=2)]
    chunk_seconds: Annotated[int, Field(ge=1, le=30)]


class VadSettings(BaseSettingsModel):
    enabled: bool
    speech_threshold: Annotated[float, Field(ge=0.0, le=1.0)]
    min_silence_duration_ms: Annotated[int, Field(ge=0)]


class WhisperSettings(BaseSettingsModel):
    model: WhisperModelSize
    device: WhisperDevice
    compute_type: WhisperComputeType


class DatabaseSettings(BaseSettingsModel):
    path: Path


class Settings(BaseSettingsModel):
    application: ApplicationSettings
    api: ApiSettings
    logging: LoggingSettings
    audio: AudioSettings
    vad: VadSettings
    whisper: WhisperSettings
    database: DatabaseSettings

    @property
    def is_development(self) -> bool:
        return (
            self.application.environment
            == ApplicationEnvironment.DEVELOPMENT
        )

    @property
    def is_production(self) -> bool:
        return (
            self.application.environment
            == ApplicationEnvironment.PRODUCTION
        )

    @property
    def is_test(self) -> bool:
        return (
            self.application.environment
            == ApplicationEnvironment.TEST
        )

__all__ = [
    "ApplicationSettings",
    "ApiSettings",
    "AudioSettings",
    "BaseSettingsModel",
    "DatabaseSettings",
    "LoggingSettings",
    "Settings",
    "VadSettings",
    "WhisperSettings",
]