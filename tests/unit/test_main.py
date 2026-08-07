from pathlib import Path

from app.main import main
from tests.unit.core.config.builders import valid_configuration_document
from tests.unit.core.config.helpers import write_configuration


def test_main_starts_application_with_configuration(
    tmp_path: Path,
) -> None:
    # Arrange
    document = valid_configuration_document()
    config_path = write_configuration(tmp_path, document)

    # Act
    main(config_path)

    # Assert
    # Reaching this point means startup completed successfully.
