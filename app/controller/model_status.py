from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from app.core.config.models import Settings
from app.models.whisper import (
    WhisperModelProvisioningState,
    WhisperModelResolver,
    WhisperModelStatus,
)


class WhisperModelStatusProvider(Protocol):
    def get_status(self) -> WhisperModelStatus:
        """Return the current configured Whisper model status."""


class ConfiguredWhisperModelStatusProvider:
    """Report local availability of the currently configured Whisper model."""

    def __init__(
        self,
        *,
        settings_loader: Callable[[], Settings],
        resolver: WhisperModelResolver,
    ) -> None:
        self._settings_loader = settings_loader
        self._resolver = resolver

    def get_status(self) -> WhisperModelStatus:
        settings = self._settings_loader()

        resolved = self._resolver.resolve(
            settings.whisper.model,
        )

        state = (
            WhisperModelProvisioningState.READY
            if resolved.ready
            else WhisperModelProvisioningState.NOT_INSTALLED
        )

        return WhisperModelStatus(
            model=resolved.model,
            path=resolved.path,
            state=state,
        )
