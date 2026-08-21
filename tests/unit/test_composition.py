from pathlib import Path
from typing import cast
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from app.application import Application
from app.audio.capture import (
    PyAudioCapture,
    WasapiInputDeviceProviderFactoryImpl,
    WasapiLoopbackDeviceProviderFactoryImpl,
)
from app.audio.contracts import AudioFormat, AudioFrame
from app.audio.protocols import AudioCapture
from app.audio.timeline import MonotonicAudioTimeline
from app.composition import (
    create_application,
    create_microphone_capture,
    create_normalizer,
    create_speech_pipeline,
    create_system_audio_capture,
    create_transcriber,
    create_vad,
)
from app.services.speech_pipeline import SpeechPipeline
from app.transcription.contracts import AudioSource
from app.transcription.faster_whisper import FasterWhisperTranscriber
from app.vad.protocols import AudioVad
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


def test_create_speech_pipeline_wires_dependencies() -> None:
    capture = MagicMock()
    normalizer = MagicMock()
    vad = MagicMock()
    assembler = MagicMock()
    transcription_executor = MagicMock()

    with patch("app.composition.SpeechPipeline") as pipeline_type:
        result = create_speech_pipeline(
            source=AudioSource.SYSTEM_AUDIO,
            capture=capture,
            normalizer=normalizer,
            vad=vad,
            assembler=assembler,
            transcription_executor=transcription_executor,
        )

    assert result is pipeline_type.return_value

    pipeline_type.assert_called_once_with(
        source=AudioSource.SYSTEM_AUDIO,
        capture=capture,
        normalizer=normalizer,
        vad=vad,
        assembler=assembler,
        transcription_executor=transcription_executor,
    )


def test_create_application_builds_production_persistence_graph(
    tmp_path: Path,
) -> None:
    # Arrange
    document = valid_configuration_document()
    document["database"]["path"] = "transcripts.db"
    config_path = write_configuration(tmp_path, document)

    vad = MagicMock(spec=AudioVad)
    capture = MagicMock(spec=AudioCapture)

    with (
        patch("app.composition.create_system_audio_capture", return_value=capture),
        patch("app.composition.create_vad", return_value=vad),
    ):
        # Act
        application = create_application(config_path)

    # Assert
    assert isinstance(application, Application)
    assert isinstance(application.pipeline, SpeechPipeline)
    assert application.capture is capture


def test_create_microphone_capture_returns_pyaudio_capture() -> None:
    timeline = MonotonicAudioTimeline()

    capture = create_microphone_capture(
        queue_capacity=100,
        timeline=timeline,
    )

    assert isinstance(capture, PyAudioCapture)


def test_create_microphone_capture_uses_input_device_provider() -> None:
    timeline = MonotonicAudioTimeline()

    capture = cast(
        PyAudioCapture,
        create_microphone_capture(
            queue_capacity=100,
            timeline=timeline,
        ),
    )

    assert isinstance(
        capture._device_provider_factory,
        WasapiInputDeviceProviderFactoryImpl,
    )


def test_create_system_audio_capture_uses_loopback_device_provider() -> None:
    timeline = MonotonicAudioTimeline()

    capture = cast(
        PyAudioCapture,
        create_system_audio_capture(
            queue_capacity=100,
            timeline=timeline,
        ),
    )

    assert isinstance(
        capture._device_provider_factory,
        WasapiLoopbackDeviceProviderFactoryImpl,
    )


def test_captures_can_share_same_timeline() -> None:
    timeline = MonotonicAudioTimeline()

    system_capture = cast(
        PyAudioCapture,
        create_system_audio_capture(
            queue_capacity=100,
            timeline=timeline,
        ),
    )
    microphone_capture = cast(
        PyAudioCapture,
        create_microphone_capture(
            queue_capacity=100,
            timeline=timeline,
        ),
    )

    assert system_capture._timeline is timeline
    assert microphone_capture._timeline is timeline


def test_create_application_shares_transcription_executor_with_pipeline(
    tmp_path: Path,
) -> None:
    # Arrange
    document = valid_configuration_document()
    config_path = write_configuration(tmp_path, document)

    capture = MagicMock(spec=AudioCapture)
    vad = MagicMock(spec=AudioVad)
    transcription_executor = MagicMock()

    with (
        patch(
            "app.composition.create_system_audio_capture",
            return_value=capture,
        ),
        patch(
            "app.composition.create_vad",
            return_value=vad,
        ),
        patch(
            "app.composition.create_transcription_executor",
            return_value=transcription_executor,
        ),
        patch("app.composition.create_speech_pipeline") as create_pipeline,
        patch("app.composition.Application") as application_type,
    ):
        # Act
        create_application(config_path)

    # Assert
    create_pipeline.assert_called_once()

    assert create_pipeline.call_args.kwargs["transcription_executor"] is transcription_executor

    application_type.assert_called_once()

    assert application_type.call_args.kwargs["transcription_executor"] is transcription_executor


def test_create_application_wires_shared_executor_and_pipeline(
    tmp_path: Path,
) -> None:
    # Arrange
    document = valid_configuration_document()
    config_path = write_configuration(tmp_path, document)

    capture = MagicMock(spec=AudioCapture)
    vad = MagicMock(spec=AudioVad)
    transcription_executor = MagicMock()

    with (
        patch(
            "app.composition.create_system_audio_capture",
            return_value=capture,
        ),
        patch(
            "app.composition.create_vad",
            return_value=vad,
        ),
        patch(
            "app.composition.create_transcription_executor",
            return_value=transcription_executor,
        ),
        patch("app.composition.create_speech_pipeline") as create_pipeline,
        patch("app.composition.Application") as application_type,
    ):
        # Act
        create_application(config_path)

    # Assert
    pipeline = create_pipeline.return_value

    assert create_pipeline.call_args.kwargs["transcription_executor"] is transcription_executor

    assert application_type.call_args.kwargs["transcription_executor"] is transcription_executor

    assert application_type.call_args.kwargs["pipeline"] is pipeline
