from pathlib import Path

import pytest

from app.core.config.constants import DEFAULT_CONFIGURATION_PATH
from app.core.config.loader import ConfigurationLoader
from app.core.config.models import Settings

EXAMPLE_CONFIGURATION_PATH = Path("config/config.example.yaml")


def test_default_configuration_loads_successfully() -> None:
    # Arrange
    loader = ConfigurationLoader(DEFAULT_CONFIGURATION_PATH)

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
    loader = ConfigurationLoader(configuration_path)

    # Act
    settings = loader.load()

    # Assert
    assert isinstance(settings, Settings)
