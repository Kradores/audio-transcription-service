from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from app.core.config.models import Settings


def valid_configuration_document() -> dict[str, Any]:
    """Return the smallest valid configuration document."""

    return {
        "application": {
            "name": "Audio Transcription Service",
            "environment": "development",
        },
        "api": {
            "host": "127.0.0.1",
            "port": 8080,
        },
        "logging": {
            "level": "INFO",
        },
        "audio": {
            "sample_rate": 16_000,
            "channels": 1,
            "chunk_seconds": 5,
        },
        "vad": {
            "enabled": True,
            "speech_threshold": 0.5,
            "min_silence_duration_ms": 500,
        },
        "whisper": {
            "model": "small",
            "device": "cpu",
            "compute_type": "int8",
        },
        "database": {
            "path": "data/transcripts.db",
        },
    }


class SettingsBuilder:
    """Builder for creating Settings test instances."""

    def __init__(self) -> None:
        self._document = deepcopy(valid_configuration_document())

    def build(self) -> Settings:
        """Build a validated Settings instance."""

        return Settings.model_validate(self._document)

    def build_document(self) -> dict[str, Any]:
        """Return the underlying configuration document."""

        return deepcopy(self._document)

    def with_api_port(self, port: int) -> SettingsBuilder:
        self._document["api"]["port"] = port
        return self

    def with_sample_rate(self, sample_rate: int) -> SettingsBuilder:
        self._document["audio"]["sample_rate"] = sample_rate
        return self

    def with_channels(self, channels: int) -> SettingsBuilder:
        self._document["audio"]["channels"] = channels
        return self

    def with_chunk_seconds(self, seconds: int) -> SettingsBuilder:
        self._document["audio"]["chunk_seconds"] = seconds
        return self

    def with_speech_threshold(self, threshold: float) -> SettingsBuilder:
        self._document["vad"]["speech_threshold"] = threshold
        return self

    def with_environment(self, environment: str) -> SettingsBuilder:
        self._document["application"]["environment"] = environment
        return self

    def with_log_level(self, level: str) -> SettingsBuilder:
        self._document["logging"]["level"] = level
        return self

    def with_database_path(self, path: str | Path) -> SettingsBuilder:
        self._document["database"]["path"] = str(path)
        return self


__all__ = [
    "SettingsBuilder",
    "valid_configuration_document",
]
