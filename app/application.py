from __future__ import annotations

from app.core.config.models import Settings


class Application:
    """Represents the running application."""

    def __init__(
        self,
        settings: Settings,
    ) -> None:
        self._settings = settings

    @property
    def settings(self) -> Settings:
        """Return the application configuration."""

        return self._settings
