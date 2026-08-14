from __future__ import annotations

from app.audio.protocols import AudioCapture, AudioNormalizer
from app.core.config.models import Settings
from app.services.speech_pipeline import SpeechPipeline
from app.transcription.protocols import Transcriber


class Application:
    """Represents the running application."""

    def __init__(
        self,
        settings: Settings,
        capture: AudioCapture,
        normalizer: AudioNormalizer,
        transcriber: Transcriber,
        pipeline: SpeechPipeline,
    ) -> None:
        self._settings = settings
        self._capture = capture
        self._normalizer = normalizer
        self._transcriber = transcriber
        self._pipeline = pipeline

    @property
    def transcriber(self) -> Transcriber:
        """Return the application transcription service."""

        return self._transcriber

    @property
    def settings(self) -> Settings:
        """Return the application configuration."""

        return self._settings

    @property
    def capture(self) -> AudioCapture:
        """Return the audio capture instance."""

        return self._capture

    @property
    def normalizer(self) -> AudioNormalizer:
        """Return the audio normalizer instance."""

        return self._normalizer

    @property
    def pipeline(self) -> SpeechPipeline:
        """Return the speech processing pipeline."""

        return self._pipeline

    async def start(self) -> None:
        """Start the application."""

        await self._pipeline.start()

    async def stop(self) -> None:
        """Stop the application."""

        await self._pipeline.stop()
