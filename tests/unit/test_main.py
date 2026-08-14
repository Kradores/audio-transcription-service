from pathlib import Path
from unittest.mock import MagicMock, patch

from app.main import main
from tests.unit.core.config.builders import valid_configuration_document
from tests.unit.core.config.helpers import write_configuration


@patch("app.composition.create_vad")
def test_main_starts_application_with_configuration(
    create_vad: MagicMock,
    tmp_path: Path,
) -> None:
    # Arrange
    document = valid_configuration_document()
    config_path = write_configuration(tmp_path, document)

    vad = MagicMock()
    create_vad.return_value = vad

    # Act
    main(config_path)

    # Assert
    # Reaching this point means startup completed successfully.
