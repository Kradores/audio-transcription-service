from collections.abc import AsyncIterator
from typing import Protocol

from app.audio.contracts import AudioFrame


class AudioCapture(Protocol):
    """Application-facing abstraction for continuous audio capture."""

    async def start(self) -> None:
        """Start capturing audio."""

    def frames(self) -> AsyncIterator[AudioFrame]:
        """Return an asynchronous stream of captured audio frames."""

    async def stop(self) -> None:
        """Stop capturing audio."""
