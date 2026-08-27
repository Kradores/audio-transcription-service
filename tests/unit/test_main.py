import asyncio
import signal
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.main import _handle_shutdown_signal, run_application


@pytest.mark.anyio
async def test_run_application_stops_gracefully_when_shutdown_is_requested(
    tmp_path: Path,
) -> None:
    # Arrange
    application = MagicMock()
    application.start = AsyncMock()
    application.stop = AsyncMock()

    shutdown_event = asyncio.Event()
    shutdown_event.set()
    runtime_finished = asyncio.Event()

    async def wait_for_runtime() -> None:
        await runtime_finished.wait()

    application.wait = AsyncMock(side_effect=wait_for_runtime)

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
    runtime_finished = asyncio.Event()

    async def wait_for_runtime() -> None:
        await runtime_finished.wait()

    application.wait = AsyncMock(side_effect=wait_for_runtime)

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


@pytest.mark.anyio
async def test_run_application_propagates_runtime_failure_and_stops_application(
    tmp_path: Path,
) -> None:
    # Arrange
    application = MagicMock()
    application.start = AsyncMock()
    application.wait = AsyncMock(
        side_effect=RuntimeError("pipeline failed"),
    )
    application.stop = AsyncMock()

    shutdown_event = asyncio.Event()

    # Act / Assert
    with (
        patch(
            "app.main.create_application",
            return_value=application,
        ),
        pytest.raises(
            RuntimeError,
            match="pipeline failed",
        ),
    ):
        await run_application(
            tmp_path / "config.yaml",
            shutdown_event=shutdown_event,
        )

    application.stop.assert_awaited_once()


def test_shutdown_signal_sets_shutdown_event() -> None:
    shutdown_event = asyncio.Event()

    _handle_shutdown_signal(
        shutdown_event,
        signal.SIGINT,
        None,
    )

    assert shutdown_event.is_set()
