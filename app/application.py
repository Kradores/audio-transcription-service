from __future__ import annotations

import sqlite3

from app.audio.protocols import AudioCapture, AudioNormalizer
from app.core.config.models import Settings
from app.services.speech_pipeline import SpeechPipeline


class Application:
    """Represents the running application."""

    def __init__(
        self,
        settings: Settings,
        capture: AudioCapture,
        normalizer: AudioNormalizer,
        pipeline: SpeechPipeline,
        database: sqlite3.Connection,
    ) -> None:
        self._settings = settings
        self._capture = capture
        self._normalizer = normalizer
        self._pipeline = pipeline
        self._database = database

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
        """Stop the application and release owned resources."""

        await self._pipeline.stop()
        self._database.close()
