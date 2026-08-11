from pathlib import Path

import numpy as np

from app.application import Application
from app.audio.contracts import AudioFormat, AudioFrame
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


def test_create_application_wires_configured_processing_sample_rate_to_normalizer(
    tmp_path: Path,
) -> None:
    # Arrange
    document = valid_configuration_document()
    document["audio"]["processing"]["sample_rate"] = 48_000
    config_path = write_configuration(tmp_path, document)

    # Act
    application = create_application(config_path)

    output = application.normalizer.process(
        AudioFrame(
            audio=np.zeros((960, 1), dtype=np.int16),
            timestamp=10.0,
            format=AudioFormat(
                sample_rate=48_000,
                channels=1,
                sample_type="int16",
            ),
        ),
    )

    # Assert
    assert len(output) == 1
    assert output[0].format.sample_rate == 48_000
    assert output[0].format.channels == 1
    assert output[0].format.sample_type == "float32"
    assert output[0].audio.shape == (960, 1)
