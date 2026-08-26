import sqlite3
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
    create_transcription_executor,
    create_vad,
    create_whisper_model,
)
from app.services.transcription_executor import TranscriptionExecutor
from app.transcription.contracts import AudioSource
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
    assert application.settings.transcription.worker_count == 2


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


@patch("app.composition.FasterWhisperTranscriber")
def test_create_transcriber_creates_configured_faster_whisper_transcriber(
    faster_whisper_transcriber: MagicMock,
) -> None:
    # Arrange
    model = MagicMock()

    # Act
    create_transcriber(model)

    # Assert
    faster_whisper_transcriber.assert_called_once_with(model)


def test_create_speech_pipeline_wires_dependencies() -> None:
    capture = MagicMock()
    normalizer = MagicMock()
    vad = MagicMock()
    assembler = MagicMock()
    transcription_segment_aggregator = MagicMock()
    transcription_executor = MagicMock()

    with patch("app.composition.SpeechPipeline") as pipeline_type:
        result = create_speech_pipeline(
            source=AudioSource.SYSTEM_AUDIO,
            capture=capture,
            normalizer=normalizer,
            vad=vad,
            assembler=assembler,
            transcription_segment_aggregator=transcription_segment_aggregator,
            transcription_executor=transcription_executor,
        )

    assert result is pipeline_type.return_value

    pipeline_type.assert_called_once_with(
        source=AudioSource.SYSTEM_AUDIO,
        capture=capture,
        normalizer=normalizer,
        vad=vad,
        assembler=assembler,
        transcription_segment_aggregator=transcription_segment_aggregator,
        transcription_executor=transcription_executor,
    )


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


def test_create_application_builds_one_conversation_pipeline(
    tmp_path: Path,
) -> None:
    # Arrange
    document = valid_configuration_document()
    config_path = write_configuration(tmp_path, document)

    capture = MagicMock(spec=AudioCapture)
    vad = MagicMock(spec=AudioVad)

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
            "app.composition.create_conversation_pipeline",
        ) as conversation_pipeline,
        patch("app.composition.Application") as application_type,
    ):
        # Act
        create_application(config_path)

    # Assert
    conversation_pipeline.assert_called_once()
    application_type.assert_called_once()


def test_create_application_builds_two_source_pipelines_with_shared_executor(
    tmp_path: Path,
) -> None:
    # Arrange
    document = valid_configuration_document()
    config_path = write_configuration(tmp_path, document)

    system_capture = MagicMock(spec=AudioCapture)
    microphone_capture = MagicMock(spec=AudioCapture)
    transcription_executor = MagicMock(spec=TranscriptionExecutor)

    with (
        patch(
            "app.composition.create_system_audio_capture",
            return_value=system_capture,
        ),
        patch(
            "app.composition.create_microphone_capture",
            return_value=microphone_capture,
        ),
        patch(
            "app.composition.create_transcription_executor",
            return_value=transcription_executor,
        ),
        patch("app.composition.create_source_pipeline") as create_source,
    ):
        create_application(config_path)

    calls = create_source.call_args_list

    assert len(calls) == 2

    assert calls[0].kwargs["source"] is AudioSource.SYSTEM_AUDIO
    assert calls[0].kwargs["capture"] is system_capture
    assert calls[0].kwargs["transcription_executor"] is transcription_executor

    assert calls[1].kwargs["source"] is AudioSource.MICROPHONE
    assert calls[1].kwargs["capture"] is microphone_capture
    assert calls[1].kwargs["transcription_executor"] is transcription_executor


@patch("app.composition.WhisperModel")
def test_create_whisper_model_uses_transcription_worker_count(
    whisper_model: MagicMock,
) -> None:
    settings = SettingsBuilder().with_transcription_worker_count(3).build()

    create_whisper_model(settings)

    whisper_model.assert_called_once_with(
        settings.whisper.model.value,
        device=settings.whisper.device.value,
        compute_type=settings.whisper.compute_type.value,
        num_workers=3,
    )


@patch("app.composition.TranscriptionExecutorImpl")
@patch("app.composition.create_transcriber")
@patch("app.composition.create_whisper_model")
def test_create_transcription_executor_creates_one_transcriber_per_worker(
    create_whisper_model: MagicMock,
    create_transcriber: MagicMock,
    transcription_executor_impl: MagicMock,
) -> None:
    settings = SettingsBuilder().with_transcription_worker_count(3).build()

    database = sqlite3.connect(":memory:")

    model = MagicMock()
    create_whisper_model.return_value = model

    transcribers = [
        MagicMock(),
        MagicMock(),
        MagicMock(),
    ]
    create_transcriber.side_effect = transcribers

    create_transcription_executor(
        database=database,
        settings=settings,
    )

    create_whisper_model.assert_called_once_with(settings)

    assert create_transcriber.call_count == 3
    assert create_transcriber.call_args_list == [
        ((model,), {}),
        ((model,), {}),
        ((model,), {}),
    ]

    transcription_executor_impl.assert_called_once()

    call = transcription_executor_impl.call_args

    assert call.kwargs["transcribers"] == tuple(transcribers)
    assert call.kwargs["queue_capacity"] == settings.transcription.queue_capacity
