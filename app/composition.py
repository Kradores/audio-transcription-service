from __future__ import annotations

from pathlib import Path

import pyaudiowpatch

from app.application import Application
from app.audio.capture import PyAudioCapture, QueuedAudioCapture, WasapiLoopbackDeviceProvider
from app.audio.normalizer import AudioNormalizerImpl
from app.audio.resampler import SoXRResamplerFactory
from app.core.config.constants import DEFAULT_CONFIGURATION_PATH
from app.core.config.loader import ConfigurationLoader
from app.core.logging import configure_logging


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
