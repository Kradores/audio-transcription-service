from __future__ import annotations

from app.audio.protocols import AudioCapture
from app.core.config.models import Settings


class Application:
    """Represents the running application."""

    def __init__(
        self,
        settings: Settings,
        capture: AudioCapture,
    ) -> None:
        self._settings = settings
        self._capture = capture

    @property
    def settings(self) -> Settings:
        """Return the application configuration."""

        return self._settings

    @property
    def capture(self) -> AudioCapture:
        """Return the audio capture instance."""

        return self._capture

    def start(self) -> None:
        """Start the application."""
