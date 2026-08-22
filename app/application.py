# app/application.py

from __future__ import annotations

import sqlite3

from app.core.config.models import Settings
from app.services.conversation_pipeline import ConversationPipeline


class Application:
    """Represents the running application."""

    def __init__(
        self,
        *,
        settings: Settings,
        conversation_pipeline: ConversationPipeline,
        database: sqlite3.Connection,
    ) -> None:
        self._settings = settings
        self._conversation_pipeline = conversation_pipeline
        self._database = database

    @property
    def settings(self) -> Settings:
        """Return the application configuration."""
        return self._settings

    async def start(self) -> None:
        """Start the application."""
        await self._conversation_pipeline.start()

    async def stop(self) -> None:
        """Stop the application and release owned resources."""
        try:
            await self._conversation_pipeline.stop()
        finally:
            self._database.close()

    async def wait(self) -> None:
        """Wait for an unexpected application runtime termination."""
        await self._conversation_pipeline.wait()
