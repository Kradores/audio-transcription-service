from __future__ import annotations

import time
from collections.abc import Callable
from typing import Protocol


class AudioTimeline(Protocol):
    """Shared monotonic timeline for one conversation session."""

    def now(self) -> float:
        """Return seconds since the conversation timeline started."""


class MonotonicAudioTimeline:
    """Conversation timeline backed by a monotonic clock."""

    def __init__(
        self,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._clock = clock
        self._origin = clock()

    def now(self) -> float:
        return self._clock() - self._origin
