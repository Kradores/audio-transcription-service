from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.controller.multiprocessing_runtime import (
    _run_runtime_process,
)
from app.controller.runtime_process import RuntimeFailedEvent


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
