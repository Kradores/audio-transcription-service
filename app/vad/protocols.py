from __future__ import annotations

from typing import Protocol

import numpy as np
from numpy.typing import NDArray

type SileroAudio = NDArray[np.float32]


class SileroVADIterator(Protocol):
    """Minimal interface required from the Silero streaming iterator."""

    def __call__(self, audio: SileroAudio) -> dict[str, int | float] | None:
        """Process an audio chunk and return an optional speech event."""

    def reset_states(self) -> None:
        """Reset the iterator state."""
