from __future__ import annotations

from typing import Any


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
