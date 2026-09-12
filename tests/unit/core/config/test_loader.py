from pathlib import Path

import pytest

from app.core.config.exceptions import ConfigurationFileNotFoundError
from app.core.config.loader import ConfigurationLoader
from tests.unit.core.config.builders import valid_configuration_document
from tests.unit.core.config.helpers import write_configuration


def test_load_raises_when_configuration_file_is_missing(
    tmp_path: Path,
) -> None:
    # Arrange
    loader = ConfigurationLoader(
        tmp_path / "missing.yaml",
    )

    # Act / Assert
    with pytest.raises(ConfigurationFileNotFoundError):
        loader.load()


def test_load_returns_settings_for_valid_configuration(
    tmp_path: Path,
) -> None:
    # Arrange
    document = valid_configuration_document()

    config_path = write_configuration(
        tmp_path,
        document,
    )

    loader = ConfigurationLoader(config_path)

    # Act
    settings = loader.load()

    # Assert
    assert settings.application.name == "Audio Transcription Service"


def test_load_resolves_slow_inference_directory_relative_to_config_file(
    tmp_path: Path,
) -> None:
    document = valid_configuration_document()

    document["whisper"]["slow_inference_capture"] = {
        "enabled": True,
        "threshold_seconds": 5.0,
        "directory": "diagnostics/slow-inference",
    }

    config_path = write_configuration(
        tmp_path,
        document,
    )

    settings = ConfigurationLoader(config_path).load()

    assert (
        settings.whisper.slow_inference_capture.directory
        == (tmp_path / "diagnostics" / "slow-inference").resolve()
    )
