from collections.abc import AsyncIterator
from typing import Protocol

from app.audio.contracts import AudioFrame, ProcessingAudioFrame


class AudioCapture(Protocol):
    """Application-facing abstraction for continuous audio capture."""

    async def start(self) -> None:
        """Start audio capture."""

    def frames(self) -> AsyncIterator[AudioFrame]:
        """Return an asynchronous stream of captured audio frames."""

    async def stop(self) -> None:
        """Stop audio capture."""


class AudioNormalizer(Protocol):
    """Application-facing abstraction for stateful audio normalization."""

    def process(
        self,
        frame: AudioFrame,
    ) -> tuple[ProcessingAudioFrame, ...]:
        """Normalize a captured frame and emit complete processing frames."""

    def flush(self) -> None:
        """Discard any incomplete trailing audio."""
