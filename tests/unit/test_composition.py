from pathlib import Path
from unittest.mock import ANY, MagicMock, patch

import numpy as np
import pytest

from app.application import Application
from app.audio.contracts import AudioFormat, AudioFrame
from app.composition import (
    create_application,
    create_normalizer,
    create_speech_pipeline,
    create_transcriber,
    create_vad,
)
from app.transcription.faster_whisper import FasterWhisperTranscriber
from app.vad.silero import SileroVADAdapter
from tests.unit.core.config.builders import SettingsBuilder, valid_configuration_document
from tests.unit.core.config.helpers import write_configuration


@patch("app.composition.create_vad")
def test_create_application_loads_configuration(
    create_vad: MagicMock,
    tmp_path: Path,
) -> None:
    # Arrange
    document = valid_configuration_document()
    config_path = write_configuration(tmp_path, document)

    vad = MagicMock()
    create_vad.return_value = vad

    # Act
    application = create_application(config_path)

    # Assert
    assert isinstance(application, Application)
    assert application.settings.application.name == "Audio Transcription Service"


@patch("app.composition.create_vad")
def test_create_application_passes_loaded_settings_to_application(
    create_vad: MagicMock,
    tmp_path: Path,
) -> None:
    # Arrange
    document = valid_configuration_document()
    config_path = write_configuration(tmp_path, document)

    vad = MagicMock()
    create_vad.return_value = vad

    # Act
    application = create_application(config_path)

    # Assert
    assert application.settings.database.path == (tmp_path / "data" / "transcripts.db").resolve()


def test_create_normalizer_wires_configured_processing_sample_rate() -> None:
    # Arrange
    settings = SettingsBuilder().with_sample_rate(48_000).build()

    # Act
    normalizer = create_normalizer(settings.audio.processing)

    output = normalizer.process(
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


def test_create_transcriber_creates_configured_faster_whisper_transcriber() -> None:
    # Arrange
    settings = SettingsBuilder().build()
    model = MagicMock()

    with patch(
        "app.composition.WhisperModel",
        return_value=model,
    ) as whisper_model:
        # Act
        transcriber = create_transcriber(settings)

    # Assert
    whisper_model.assert_called_once_with(
        "small",
        device="cpu",
        compute_type="int8",
    )
    assert isinstance(transcriber, FasterWhisperTranscriber)


def test_create_transcriber_passes_configured_whisper_settings() -> None:
    # Arrange
    settings = (
        SettingsBuilder()
        .with_whisper_model("medium")
        .with_whisper_device("cuda")
        .with_whisper_compute_type("float16")
        .build()
    )
    model = MagicMock()

    with patch(
        "app.composition.WhisperModel",
        return_value=model,
    ) as whisper_model:
        # Act
        create_transcriber(settings)

    # Assert
    whisper_model.assert_called_once_with(
        "medium",
        device="cuda",
        compute_type="float16",
    )


@patch("app.composition.create_vad")
@patch("app.composition.create_transcriber")
def test_create_application_wires_transcriber(
    create_transcriber: MagicMock,
    create_vad: MagicMock,
    tmp_path: Path,
) -> None:
    # Arrange
    document = valid_configuration_document()
    config_path = write_configuration(tmp_path, document)

    vad = MagicMock()
    transcriber = MagicMock()

    create_vad.return_value = vad
    create_transcriber.return_value = transcriber

    # Act
    application = create_application(config_path)

    # Assert
    assert application.transcriber is transcriber


@patch("app.composition.create_vad")
@patch("app.composition.create_speech_pipeline")
def test_create_application_wires_speech_pipeline(
    create_speech_pipeline: MagicMock,
    create_vad: MagicMock,
    tmp_path: Path,
) -> None:
    # Arrange
    document = valid_configuration_document()
    config_path = write_configuration(tmp_path, document)

    vad = MagicMock()
    pipeline = MagicMock()

    create_vad.return_value = vad
    create_speech_pipeline.return_value = pipeline
    
    # Act
    application = create_application(config_path)

    # Assert
    assert application.pipeline is pipeline


def test_create_speech_pipeline_passes_dependencies_to_pipeline() -> None:
    capture = MagicMock()
    normalizer = MagicMock()
    vad = MagicMock()
    assembler = MagicMock()
    transcriber = MagicMock()

    with patch(
        "app.composition.SpeechPipeline",
    ) as pipeline_type:
        result = create_speech_pipeline(
            capture=capture,
            normalizer=normalizer,
            vad=vad,
            assembler=assembler,
            transcriber=transcriber,
        )

    assert result is pipeline_type.return_value

    pipeline_type.assert_called_once_with(
        capture=capture,
        normalizer=normalizer,
        vad=vad,
        assembler=assembler,
        transcriber=transcriber,
        on_result=ANY,
    )
