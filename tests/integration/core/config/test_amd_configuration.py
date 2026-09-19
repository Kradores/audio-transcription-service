from __future__ import annotations

from pathlib import Path

from app.core.config.enums import (
    WhisperComputeType,
    WhisperDevice,
    WhisperRuntime,
)
from app.core.config.loader import ConfigurationLoader
from app.core.runtime_paths import create_development_runtime_paths


def test_amd_configuration_is_valid() -> None:
    repository_root = Path(__file__).resolve().parents[4]

    config_path = repository_root / "config" / "config.amd.example.yaml"

    runtime_paths = create_development_runtime_paths(
        repository_root,
        config_path=config_path,
    )

    settings = ConfigurationLoader(
        runtime_paths,
    ).load()

    assert settings.whisper.runtime is WhisperRuntime.THEROCK
    assert settings.whisper.device is WhisperDevice.CUDA
    assert settings.whisper.compute_type is WhisperComputeType.FLOAT16
    assert settings.transcription.worker_count == 1
