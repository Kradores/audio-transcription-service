from __future__ import annotations

from pathlib import Path

import pyaudiowpatch
from silero_vad import VADIterator, load_silero_vad

from app.application import Application
from app.audio.capture import PyAudioCapture, QueuedAudioCapture, WasapiLoopbackDeviceProvider
from app.audio.normalizer import AudioNormalizerImpl
from app.audio.protocols import AudioVad
from app.audio.resampler import SoXRResamplerFactory
from app.core.config.constants import DEFAULT_CONFIGURATION_PATH
from app.core.config.loader import ConfigurationLoader
from app.core.config.models import Settings
from app.core.logging import configure_logging
from app.vad.silero import SileroVADAdapter


def create_application(
    config_path: Path = DEFAULT_CONFIGURATION_PATH,
) -> Application:
    """Create and configure the application."""

    settings = ConfigurationLoader(config_path).load()

    configure_logging(settings.logging)

    audio = pyaudiowpatch.PyAudio()
    device_provider = WasapiLoopbackDeviceProvider(audio)
    transport = QueuedAudioCapture(max_queue_size=settings.audio.capture.queue_capacity)

    capture = PyAudioCapture(
        audio=audio,
        device_provider=device_provider,
        transport=transport,
    )

    resampler_factory = SoXRResamplerFactory()

    normalizer = AudioNormalizerImpl(
        settings=settings.audio.processing,
        resampler_factory=resampler_factory,
    )

    return Application(
        settings=settings,
        capture=capture,
        normalizer=normalizer,
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
