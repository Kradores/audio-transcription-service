from __future__ import annotations

from collections.abc import Callable
from typing import Protocol


class AudioDeviceMonitor(Protocol):
    """Observe changes to the system default audio output device."""

    def start(self) -> None:
        """Start monitoring for default output-device changes."""

    def stop(self) -> None:
        """Stop monitoring."""

    def set_change_handler(
        self,
        handler: Callable[[str | None], None],
    ) -> None:
        """Set the handler invoked when the default output device changes."""