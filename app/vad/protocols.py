from __future__ import annotations

from typing import Protocol

import numpy as np
from numpy.typing import NDArray

from app.audio.contracts import ProcessingAudioFrame, SpeechEnd, SpeechSegment, SpeechStart

type SileroAudio = NDArray[np.float32]


class SileroVADIterator(Protocol):
    """Minimal interface required from the Silero streaming iterator."""

    def __call__(self, audio: SileroAudio) -> dict[str, int | float] | None:
        """Process an audio chunk and return an optional speech event."""

    def reset_states(self) -> None:
        """Reset the iterator state."""


class AudioVad(Protocol):
    """Application-facing voice activity detection contract."""

    def process(
        self,
        frame: ProcessingAudioFrame,
    ) -> tuple[SpeechStart | SpeechEnd, ...]:
        """Process one normalized frame and return detected transitions."""

    def reset(self) -> None:
        """Reset VAD state to the initial non-speech state."""


class SpeechSegmentAssembler(Protocol):
    """Application-facing speech segment assembly contract."""

    def process(
        self,
        frame: ProcessingAudioFrame,
        events: tuple[SpeechStart | SpeechEnd, ...],
    ) -> tuple[SpeechSegment, ...]:
        """Process one normalized frame and its VAD events."""

    def reset(self) -> None:
        """Discard all state and return to the idle state."""

    def flush(self) -> tuple[SpeechSegment, ...]:
        """Discard incomplete state and return to the idle state."""
