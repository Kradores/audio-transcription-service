from __future__ import annotations

from app.audio.protocols import AudioCapture, AudioNormalizer
from app.core.config.models import Settings


class Application:
    """Represents the running application."""

    def __init__(
        self,
        settings: Settings,
        capture: AudioCapture,
        normalizer: AudioNormalizer,
    ) -> None:
        self._settings = settings
        self._capture = capture
        self._normalizer = normalizer

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

    async def start(self) -> None:
        """Start the application."""
        await self._capture.start()

    async def stop(self) -> None:
        """Stop the application."""
        await self._capture.stop()
