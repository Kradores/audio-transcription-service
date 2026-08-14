from __future__ import annotations

from pathlib import Path

import pyaudiowpatch
from faster_whisper import WhisperModel  # type: ignore[import-untyped]
from silero_vad import VADIterator, load_silero_vad

from app.application import Application
from app.audio.capture import PyAudioCapture, QueuedAudioCapture, WasapiLoopbackDeviceProvider
from app.audio.normalizer import AudioNormalizerImpl
from app.audio.protocols import AudioCapture, AudioNormalizer
from app.audio.resampler import SoXRResamplerFactory
from app.core.config.constants import DEFAULT_CONFIGURATION_PATH
from app.core.config.loader import ConfigurationLoader
from app.core.config.models import AudioProcessingSettings, Settings
from app.core.logging import configure_logging
from app.transcription.faster_whisper import FasterWhisperTranscriber
from app.transcription.protocols import Transcriber
from app.vad.protocols import AudioVad
from app.vad.silero import SileroVADAdapter


def create_application(
    config_path: Path = DEFAULT_CONFIGURATION_PATH,
) -> Application:
    """Create and configure the application."""

    settings = ConfigurationLoader(config_path).load()

    capture = create_capture(settings.audio.capture.queue_capacity)
    normalizer = create_normalizer(settings.audio.processing)
    transcriber = create_transcriber(settings)

    configure_logging(settings.logging)

    return Application(
        settings=settings,
        capture=capture,
        normalizer=normalizer,
        transcriber=transcriber,
    )


def create_capture(queue_capacity: int) -> AudioCapture:
    """Create the configured audio capture."""

    audio = pyaudiowpatch.PyAudio()
    device_provider = WasapiLoopbackDeviceProvider(audio)
    transport = QueuedAudioCapture(max_queue_size=queue_capacity)

    return PyAudioCapture(
        audio=audio,
        device_provider=device_provider,
        transport=transport,
    )


def create_vad(settings: Settings) -> AudioVad | None:
    """Create the configured voice activity detector."""
    if not settings.vad.enabled:
        return None

    if settings.audio.processing.sample_rate != 16_000:
        raise ValueError(
            "Silero VAD requires audio.processing.sample_rate to be 16000",
        )

    model = load_silero_vad()

    iterator = VADIterator(
        model,
        threshold=settings.vad.speech_threshold,
        sampling_rate=settings.audio.processing.sample_rate,
        min_silence_duration_ms=settings.vad.min_silence_duration_ms,
        speech_pad_ms=0,
    )

    return SileroVADAdapter(iterator)


def create_normalizer(settings: AudioProcessingSettings) -> AudioNormalizer:
    """Create the configured Audio Normalizer"""
    resampler_factory = SoXRResamplerFactory()

    return AudioNormalizerImpl(
        settings=settings,
        resampler_factory=resampler_factory,
    )


def create_whisper_model(settings: Settings) -> WhisperModel:
    """Create the configured Faster-Whisper model."""
    return WhisperModel(
        settings.whisper.model.value,
        device=settings.whisper.device.value,
        compute_type=settings.whisper.compute_type.value,
    )


def create_transcriber(settings: Settings) -> Transcriber:
    """Create the configured transcription service."""
    model = create_whisper_model(settings)

    return FasterWhisperTranscriber(model)
