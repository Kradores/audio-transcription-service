from pathlib import Path

import pytest

from app.core.config.exceptions import ConfigurationFileNotFoundError
from app.core.config.loader import ConfigurationLoader
from app.core.runtime_paths import create_development_runtime_paths
from tests.unit.core.config.builders import valid_configuration_document
from tests.unit.core.config.helpers import write_configuration


def test_load_raises_when_configuration_file_is_missing(
    tmp_path: Path,
) -> None:
    runtime_paths = create_development_runtime_paths(
        tmp_path,
        config_path=tmp_path / "missing.yaml",
    )
    loader = ConfigurationLoader(runtime_paths)

    with pytest.raises(ConfigurationFileNotFoundError):
        loader.load()


def test_load_returns_settings_for_valid_configuration(
    tmp_path: Path,
) -> None:
    document = valid_configuration_document()
    config_path = write_configuration(
        tmp_path,
        document,
    )
    runtime_paths = create_development_runtime_paths(
        tmp_path,
        config_path=config_path,
    )
    loader = ConfigurationLoader(runtime_paths)

    settings = loader.load()

    assert settings.application.name == "Audio Transcription Service"


def test_load_resolves_runtime_paths_against_runtime_root(
    tmp_path: Path,
) -> None:
    config_directory = tmp_path / "config"
    config_directory.mkdir()

    document = valid_configuration_document()
    document["whisper"]["slow_inference_capture"] = {
        "enabled": True,
        "threshold_seconds": 5.0,
        "directory": "diagnostics/slow-inference",
    }

    config_path = write_configuration(
        config_directory,
        document,
    )
    runtime_paths = create_development_runtime_paths(
        tmp_path,
        config_path=config_path,
    )

    settings = ConfigurationLoader(runtime_paths).load()

    assert settings.database.path == (tmp_path / "data" / "transcripts.db").resolve()
    assert (
        settings.logging.file.path
        == (tmp_path / "logs" / "audio-transcription-service.log").resolve()
    )
    assert (
        settings.whisper.slow_inference_capture.directory
        == (tmp_path / "diagnostics" / "slow-inference").resolve()
    )


def test_load_preserves_absolute_runtime_paths(
    tmp_path: Path,
) -> None:
    document = valid_configuration_document()
    absolute_database_path = (tmp_path / "custom" / "transcripts.db").resolve()
    absolute_log_path = (tmp_path / "custom" / "application.log").resolve()
    absolute_diagnostics_path = (tmp_path / "custom" / "slow-inference").resolve()

    document["database"]["path"] = str(absolute_database_path)
    document["logging"]["file"]["path"] = str(absolute_log_path)
    document["whisper"]["slow_inference_capture"] = {
        "enabled": True,
        "threshold_seconds": 5.0,
        "directory": str(absolute_diagnostics_path),
    }

    config_path = write_configuration(
        tmp_path,
        document,
    )
    runtime_paths = create_development_runtime_paths(
        tmp_path,
        config_path=config_path,
    )

    settings = ConfigurationLoader(runtime_paths).load()

    assert settings.database.path == absolute_database_path
    assert settings.logging.file.path == absolute_log_path
    assert settings.whisper.slow_inference_capture.directory == absolute_diagnostics_path
