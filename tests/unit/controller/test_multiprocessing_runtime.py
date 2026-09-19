from __future__ import annotations

from collections.abc import Callable
from typing import cast
from unittest.mock import MagicMock, call, patch

import pytest

from app.controller.multiprocessing_runtime import (
    _run_runtime_process,
    _run_runtime_process_async,
)
from app.controller.runtime_process import (
    RuntimeFailedEvent,
    RuntimeGraphicsAdaptersObservedEvent,
    RuntimeStartedEvent,
    RuntimeTranscriptionObservedEvent,
)
from app.core.config.models import Settings
from app.observability.hardware import (
    GraphicsAdapterInfo,
    GraphicsAdaptersObservation,
)
from app.observability.transcription_runtime import (
    CTranslate2CapabilitiesObservation,
    TranscriptionRuntimeObservation,
)
from tests.unit.core.config.builders import SettingsBuilder


@patch(
    "app.controller.multiprocessing_runtime.asyncio.run",
    side_effect=RuntimeError("startup failed"),
)
def test_runtime_process_publishes_failure_and_exits_cleanly(
    run: MagicMock,
) -> None:
    runtime_paths = MagicMock()
    shutdown_signal = MagicMock()
    status_queue = MagicMock()

    with pytest.raises(SystemExit) as exc_info:
        _run_runtime_process(
            runtime_paths,
            None,
            shutdown_signal,
            status_queue,
        )

    assert exc_info.value.code == 1

    status_queue.put.assert_called_once_with(
        RuntimeFailedEvent(
            message="RuntimeError: startup failed",
        )
    )


@pytest.mark.anyio
@patch(
    "app.main.run_application",
)
@patch(
    "app.observability.windows_video_controller.WindowsVideoControllerObserver.observe",
)
async def test_runtime_child_publishes_graphics_observation(
    observe: MagicMock,
    run_application: MagicMock,
) -> None:
    settings = SettingsBuilder().build()
    observation = GraphicsAdaptersObservation.success(
        (
            GraphicsAdapterInfo(
                name="AMD Radeon RX 6800M",
                driver_version="32.0.21045.5002",
                pnp_device_id="PCI\\VEN_1002",
            ),
        )
    )

    observe.return_value = observation

    async def run_application_side_effect(
        *args: object,
        **kwargs: object,
    ) -> None:
        del args

        on_started = cast(
            Callable[[Settings], None],
            kwargs["on_started"],
        )

        on_started(settings)

    run_application.side_effect = run_application_side_effect

    shutdown_signal = MagicMock()
    shutdown_signal.is_set.return_value = False

    status_queue = MagicMock()

    await _run_runtime_process_async(
        runtime_paths=MagicMock(),
        nvidia_runtime_directory=None,
        shutdown_signal=shutdown_signal,
        status_queue=status_queue,
    )

    events = [queued_call.args[0] for queued_call in status_queue.put.call_args_list]

    assert events[0] == RuntimeGraphicsAdaptersObservedEvent(
        observation=observation,
    )

    assert isinstance(
        events[1],
        RuntimeStartedEvent,
    )


@pytest.mark.anyio
@patch(
    "app.observability.ctranslate2_runtime.CTranslate2RuntimeObserver.observe",
)
@patch(
    "app.main.run_application",
)
async def test_runtime_child_publishes_transcription_observation_after_start(
    run_application: MagicMock,
    observe_runtime: MagicMock,
) -> None:
    settings = SettingsBuilder().build()

    observation = TranscriptionRuntimeObservation(
        runtime=settings.whisper.runtime,
        device=settings.whisper.device,
        configured_compute_type=(settings.whisper.compute_type),
        initialized=True,
        ctranslate2=(
            CTranslate2CapabilitiesObservation.success(
                cuda_device_count=None,
                supported_compute_types=(
                    "float32",
                    "int8",
                ),
            )
        ),
    )

    observe_runtime.return_value = observation

    async def run_application_side_effect(
        *args: object,
        **kwargs: object,
    ) -> None:
        del args

        on_started = cast(
            Callable[[Settings], None],
            kwargs["on_started"],
        )

        on_started(settings)

    run_application.side_effect = run_application_side_effect

    shutdown_signal = MagicMock()
    shutdown_signal.is_set.return_value = False

    status_queue = MagicMock()

    await _run_runtime_process_async(
        runtime_paths=MagicMock(),
        nvidia_runtime_directory=None,
        shutdown_signal=shutdown_signal,
        status_queue=status_queue,
    )

    observe_runtime.assert_called_once_with(
        runtime=settings.whisper.runtime,
        device=settings.whisper.device,
        compute_type=settings.whisper.compute_type,
    )

    assert status_queue.put.call_args_list[-2:] == [
        call(
            RuntimeStartedEvent(),
        ),
        call(
            RuntimeTranscriptionObservedEvent(
                observation=observation,
            )
        ),
    ]


@pytest.mark.anyio
@patch(
    "app.observability.ctranslate2_runtime.CTranslate2RuntimeObserver.observe",
    side_effect=RuntimeError(
        "diagnostic observation exploded",
    ),
)
@patch(
    "app.main.run_application",
)
async def test_runtime_observation_failure_does_not_prevent_started_event(
    run_application: MagicMock,
    observe_runtime: MagicMock,
) -> None:
    settings = SettingsBuilder().build()

    async def run_application_side_effect(
        *args: object,
        **kwargs: object,
    ) -> None:
        del args

        on_started = cast(
            Callable[[Settings], None],
            kwargs["on_started"],
        )

        on_started(settings)

    run_application.side_effect = run_application_side_effect

    status_queue = MagicMock()

    await _run_runtime_process_async(
        runtime_paths=MagicMock(),
        nvidia_runtime_directory=None,
        shutdown_signal=MagicMock(),
        status_queue=status_queue,
    )

    events = [call.args[0] for call in status_queue.put.call_args_list]

    assert isinstance(
        events[-2],
        RuntimeStartedEvent,
    )

    assert isinstance(
        events[0],
        RuntimeGraphicsAdaptersObservedEvent,
    )

    assert isinstance(
        events[1],
        RuntimeStartedEvent,
    )

    assert isinstance(
        events[2],
        RuntimeTranscriptionObservedEvent,
    )

    diagnostic_event = events[-1]

    assert isinstance(
        diagnostic_event,
        RuntimeTranscriptionObservedEvent,
    )

    assert diagnostic_event.observation.ctranslate2.available is False

    assert diagnostic_event.observation.ctranslate2.error_type == "RuntimeError"

    assert diagnostic_event.observation.ctranslate2.error == ("diagnostic observation exploded")
