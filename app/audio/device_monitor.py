from __future__ import annotations

from collections.abc import Callable
from typing import Protocol


class AudioDeviceMonitor(Protocol):
    """Observe changes to a selected system default audio endpoint."""

    def start(self) -> None:
        """Start monitoring for selected default-device changes."""

    def stop(self) -> None:
        """Stop monitoring."""

    def set_change_handler(
        self,
        handler: Callable[[str | None], None],
    ) -> None:
        """Set the handler invoked when the selected default device changes."""
