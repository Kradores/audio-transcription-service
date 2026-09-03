from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from app.core.config.enums import TranscriptionLanguageMode
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
            "file": {
                "enabled": True,
                "path": "logs/audio-transcription-service.log",
                "max_bytes": 10485760,
                "backup_count": 5,
            },
        },
        "audio": {
            "capture": {
                "queue_capacity": 100,
            },
            "processing": {
                "sample_rate": 16_000,
                "channels": 1,
            },
            "segmentation": {
                "pre_roll_ms": 200,
                "post_roll_ms": 200,
                "target_duration_seconds": 3,
                "max_duration_seconds": 5,
            },
        },
        "transcription": {
            "queue_capacity": 10,
            "worker_count": 2,
            "language": {
                "mode": "auto",
            },
            "aggregation": {
                "enabled": True,
                "target_duration_seconds": 5.0,
                "max_duration_seconds": 10.0,
                "max_gap_seconds": 1.5,
                "max_wait_seconds": 2.0,
            },
        },
        "vad": {
            "enabled": True,
            "speech_threshold": 0.5,
            "min_silence_duration_ms": 500,
        },
        "whisper": {
            "model": "small",
            "runtime": "default",
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
        self._document["audio"]["processing"]["sample_rate"] = sample_rate
        return self

    def with_channels(self, channels: int) -> SettingsBuilder:
        self._document["audio"]["processing"]["channels"] = channels
        return self

    def with_capture_queue_capacity(self, capacity: int) -> SettingsBuilder:
        self._document["audio"]["capture"]["queue_capacity"] = capacity
        return self

    def with_target_duration_seconds(self, seconds: int) -> SettingsBuilder:
        self._document["audio"]["segmentation"]["target_duration_seconds"] = seconds
        return self

    def with_max_duration_seconds(self, seconds: int) -> SettingsBuilder:
        self._document["audio"]["segmentation"]["max_duration_seconds"] = seconds
        return self

    def with_pre_roll_ms(self, milliseconds: int) -> SettingsBuilder:
        self._document["audio"]["segmentation"]["pre_roll_ms"] = milliseconds
        return self

    def with_post_roll_ms(self, milliseconds: int) -> SettingsBuilder:
        self._document["audio"]["segmentation"]["post_roll_ms"] = milliseconds
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

    def with_vad_enabled(self, enabled: bool) -> SettingsBuilder:
        self._document["vad"]["enabled"] = enabled
        return self

    def with_whisper_runtime(self, runtime: str) -> SettingsBuilder:
        self._document["whisper"]["runtime"] = runtime
        return self

    def with_whisper_model(self, model: str) -> SettingsBuilder:
        self._document["whisper"]["model"] = model
        return self

    def with_whisper_device(self, device: str) -> SettingsBuilder:
        self._document["whisper"]["device"] = device
        return self

    def with_whisper_compute_type(self, compute_type: str) -> SettingsBuilder:
        self._document["whisper"]["compute_type"] = compute_type
        return self

    def with_transcription_queue_capacity(self, capacity: int) -> SettingsBuilder:
        self._document["transcription"]["queue_capacity"] = capacity
        return self

    def with_aggregation_enabled(self, enabled: bool) -> SettingsBuilder:
        self._document["transcription"]["aggregation"]["enabled"] = enabled
        return self

    def with_aggregation_target_duration_seconds(
        self,
        seconds: float,
    ) -> SettingsBuilder:
        self._document["transcription"]["aggregation"]["target_duration_seconds"] = seconds
        return self

    def with_aggregation_max_duration_seconds(
        self,
        seconds: float,
    ) -> SettingsBuilder:
        self._document["transcription"]["aggregation"]["max_duration_seconds"] = seconds
        return self

    def with_aggregation_max_gap_seconds(
        self,
        seconds: float,
    ) -> SettingsBuilder:
        self._document["transcription"]["aggregation"]["max_gap_seconds"] = seconds
        return self

    def with_aggregation_max_wait_seconds(
        self,
        seconds: float,
    ) -> SettingsBuilder:
        self._document["transcription"]["aggregation"]["max_wait_seconds"] = seconds
        return self

    def with_transcription_worker_count(self, worker_count: int) -> SettingsBuilder:
        self._document["transcription"]["worker_count"] = worker_count
        return self

    def with_adaptive_transcription_language(
        self, adaptive_language: dict[str, Any] | None = None
    ) -> SettingsBuilder:
        if adaptive_language is None:
            adaptive_language = {
                "mode": TranscriptionLanguageMode.ADAPTIVE,
                "initial_language": None,
                "min_probe_duration_seconds": 3.0,
                "switch_probability_threshold": 0.85,
                "switch_confirmations": 2,
            }
        self._document["transcription"]["language"] = adaptive_language
        return self


__all__ = [
    "SettingsBuilder",
    "valid_configuration_document",
]
