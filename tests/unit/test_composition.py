from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from app.application import Application
from app.audio.contracts import AudioFormat, AudioFrame
from app.composition import create_application, create_vad
from app.vad.silero import SileroVADAdapter
from tests.unit.core.config.builders import SettingsBuilder, valid_configuration_document
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


def test_create_vad_returns_none_when_disabled() -> None:
    # Arrange
    settings = SettingsBuilder().with_vad_enabled(False).build()

    # Act
    result = create_vad(settings)

    # Assert
    assert result is None


def test_create_vad_creates_silero_vad_when_enabled() -> None:
    # Arrange
    settings = SettingsBuilder().build()
    model = MagicMock()
    iterator = MagicMock()

    with (
        patch("app.composition.load_silero_vad", return_value=model) as load_model,
        patch("app.composition.VADIterator", return_value=iterator) as vad_iterator,
    ):
        # Act
        result = create_vad(settings)

    # Assert
    assert isinstance(result, SileroVADAdapter)
    load_model.assert_called_once_with()
    vad_iterator.assert_called_once_with(
        model,
        threshold=0.5,
        sampling_rate=16_000,
        min_silence_duration_ms=500,
        speech_pad_ms=0,
    )


def test_create_vad_passes_configured_vad_settings_to_silero() -> None:
    # Arrange
    settings = SettingsBuilder().with_speech_threshold(0.75).build()
    model = MagicMock()
    iterator = MagicMock()

    with (
        patch("app.composition.load_silero_vad", return_value=model),
        patch("app.composition.VADIterator", return_value=iterator) as vad_iterator,
    ):
        # Act
        create_vad(settings)

    # Assert
    vad_iterator.assert_called_once_with(
        model,
        threshold=0.75,
        sampling_rate=16_000,
        min_silence_duration_ms=500,
        speech_pad_ms=0,
    )


def test_create_vad_rejects_incompatible_processing_sample_rate() -> None:
    # Arrange
    settings = SettingsBuilder().with_sample_rate(48_000).build()

    # Act / Assert
    with (
        patch("app.composition.load_silero_vad") as load_model,
        pytest.raises(
            ValueError,
            match="Silero VAD requires audio.processing.sample_rate to be 16000",
        ),
    ):
        create_vad(settings)

    load_model.assert_not_called()
