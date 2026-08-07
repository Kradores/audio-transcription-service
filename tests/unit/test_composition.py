from pathlib import Path

from app.application import Application
from app.composition import create_application
from tests.unit.core.config.builders import valid_configuration_document
from tests.unit.core.config.helpers import write_configuration


def test_create_application_loads_configuration(
    tmp_path: Path,
) -> None:
    # Arrange
    document = valid_configuration_document()
    config_path = write_configuration(tmp_path, document)

    # Act
    application = create_application(config_path)

    # Assert
    assert isinstance(application, Application)
    assert application.settings.application.name == "Audio Transcription Service"


def test_create_application_passes_loaded_settings_to_application(
    tmp_path: Path,
) -> None:
    # Arrange
    document = valid_configuration_document()
    config_path = write_configuration(tmp_path, document)

    # Act
    application = create_application(config_path)

    # Assert
    assert application.settings.database.path == (tmp_path / "data" / "transcripts.db").resolve()
