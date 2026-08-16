from collections.abc import AsyncIterator, Callable
from typing import Protocol

from app.audio.contracts import (
    AudioFrame,
    Float32Audio,
    ProcessingAudioFrame,
)


class AudioCapture(Protocol):
    """Application-facing abstraction for continuous audio capture."""

    async def start(self) -> None:
        """Start audio capture."""

    def frames(self) -> AsyncIterator[AudioFrame]:
        """Return an asynchronous stream of captured audio frames."""

    def set_discontinuity_handler(
        self,
        handler: Callable[[], None],
    ) -> None:
        """Register the handler notified when capture continuity is lost."""

    async def stop(self) -> None:
        """Stop audio capture."""


class AudioNormalizer(Protocol):
    """Application-facing abstraction for stateful audio normalization."""

    def process(
        self,
        frame: AudioFrame,
    ) -> tuple[ProcessingAudioFrame, ...]:
        """Normalize a captured frame and emit complete processing frames."""

    def reset(self) -> None:
        """Discard all state caused by the previous capture continuity."""

    def flush(self) -> tuple[ProcessingAudioFrame, ...]:
        """Flush the resampler and emit any final complete processing frames."""


class AudioResampler(Protocol):
    """Application-facing abstraction for streaming audio resampling."""

    def process(self, audio: Float32Audio) -> Float32Audio:
        """Resample an audio block."""

    def flush(self) -> Float32Audio:
        """Flush buffered resampler output."""

    def reset(self) -> None:
        """Reset the resampler state."""


class AudioResamplerFactory(Protocol):
    """Creates resamplers for a specific input/output format."""

    def create(
        self,
        input_sample_rate: int,
        output_sample_rate: int,
        channels: int,
    ) -> AudioResampler:
        """Create a streaming resampler for the requested rates."""
