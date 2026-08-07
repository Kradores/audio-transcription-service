from app.application import Application
from tests.unit.core.config.builders import SettingsBuilder


def test_application_exposes_provided_settings() -> None:
    # Arrange
    settings = SettingsBuilder().build()

    # Act
    application = Application(settings)

    # Assert
    assert application.settings is settings
