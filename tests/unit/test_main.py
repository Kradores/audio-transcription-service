import asyncio
import signal
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.config.models import Settings
from app.core.runtime_paths import create_development_runtime_paths
from app.main import _handle_shutdown_signal, run_application
from tests.unit.core.config.builders import SettingsBuilder


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
            create_development_runtime_paths(tmp_path),
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
                create_development_runtime_paths(tmp_path),
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
            create_development_runtime_paths(tmp_path),
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


@pytest.mark.anyio
async def test_run_application_notifies_after_successful_start(
    tmp_path: Path,
) -> None:
    events: list[str] = []

    application = MagicMock()
    settings = SettingsBuilder().build()
    application.settings = settings

    async def start_application() -> None:
        events.append("application-started")

    application.start = AsyncMock(
        side_effect=start_application,
    )
    application.stop = AsyncMock()

    shutdown_event = asyncio.Event()
    shutdown_event.set()

    application.wait = AsyncMock()

    observed_settings: list[Settings] = []

    def on_started(
        started_settings: Settings,
    ) -> None:
        events.append("startup-notified")
        observed_settings.append(started_settings)

    with patch(
        "app.main.create_application",
        return_value=application,
    ):
        await run_application(
            create_development_runtime_paths(tmp_path),
            shutdown_event=shutdown_event,
            on_started=on_started,
        )

    assert events == [
        "application-started",
        "startup-notified",
    ]

    assert observed_settings == [
        settings,
    ]


@pytest.mark.anyio
async def test_run_application_does_not_notify_when_start_fails(
    tmp_path: Path,
) -> None:
    application = MagicMock()
    application.start = AsyncMock(
        side_effect=RuntimeError("startup failed"),
    )
    application.stop = AsyncMock()

    on_started = MagicMock()

    with (
        patch(
            "app.main.create_application",
            return_value=application,
        ),
        pytest.raises(
            RuntimeError,
            match="startup failed",
        ),
    ):
        await run_application(
            create_development_runtime_paths(tmp_path),
            on_started=on_started,
        )

    on_started.assert_not_called()
    application.stop.assert_awaited_once()
