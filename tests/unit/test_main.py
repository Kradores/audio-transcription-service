import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.main import run_application


@pytest.mark.anyio
async def test_run_application_starts_and_stops_application(
    tmp_path: Path,
) -> None:
    # Arrange
    application = MagicMock()
    application.start = AsyncMock()
    application.stop = AsyncMock()

    shutdown_event = asyncio.Event()
    shutdown_event.set()

    with patch(
        "app.main.create_application",
        return_value=application,
    ):
        # Act
        await run_application(
            tmp_path / "config.yaml",
            shutdown_event=shutdown_event,
        )

    # Assert
    application.start.assert_awaited_once()
    application.stop.assert_awaited_once()


@pytest.mark.anyio
async def test_run_application_stops_application_when_cancelled(
    tmp_path: Path,
) -> None:
    application = MagicMock()
    application.start = AsyncMock()
    application.stop = AsyncMock()

    shutdown_event = asyncio.Event()

    with patch(
        "app.main.create_application",
        return_value=application,
    ):
        task = asyncio.create_task(
            run_application(
                tmp_path / "config.yaml",
                shutdown_event=shutdown_event,
            )
        )

        await asyncio.sleep(0)

        task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await task

    application.start.assert_awaited_once()
    application.stop.assert_awaited_once()