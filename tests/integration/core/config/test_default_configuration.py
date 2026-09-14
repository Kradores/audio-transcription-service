from pathlib import Path

import pytest

from app.core.config.constants import DEFAULT_CONFIGURATION_PATH
from app.core.config.loader import ConfigurationLoader
from app.core.config.models import Settings
from app.core.runtime_paths import create_development_runtime_paths

EXAMPLE_CONFIGURATION_PATH = DEFAULT_CONFIGURATION_PATH.with_name("config.example.yaml")


def test_default_configuration_loads_successfully() -> None:
    # Arrange
    loader = ConfigurationLoader(create_development_runtime_paths())

    # Act
    settings = loader.load()

    # Assert
    assert isinstance(settings, Settings)


@pytest.mark.parametrize(
    "configuration_path",
    [
        DEFAULT_CONFIGURATION_PATH,
        EXAMPLE_CONFIGURATION_PATH,
    ],
)
def test_repository_configuration_loads_successfully(
    configuration_path: Path,
) -> None:
    # Arrange
    loader = ConfigurationLoader(
        create_development_runtime_paths(
            config_path=configuration_path,
        )
    )

    # Act
    settings = loader.load()

    # Assert
    assert isinstance(settings, Settings)
