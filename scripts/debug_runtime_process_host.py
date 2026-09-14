from __future__ import annotations

import time

from app.controller.multiprocessing_runtime import (
    MultiprocessingRuntimeProcessSessionFactory,
)
from app.controller.runtime_process import (
    RuntimeProcessHost,
    RuntimeProcessState,
)
from app.core.runtime_paths import create_development_runtime_paths

POLL_INTERVAL_SECONDS = 0.1
START_TIMEOUT_SECONDS = 60.0
STOP_TIMEOUT_SECONDS = 30.0


def wait_for_state(
    host: RuntimeProcessHost,
    *,
    expected: RuntimeProcessState,
    timeout_seconds: float,
) -> None:
    deadline = time.monotonic() + timeout_seconds

    while time.monotonic() < deadline:
        snapshot = host.refresh()

        print(
            "runtime "
            f"state={snapshot.state.value} "
            f"pid={snapshot.pid} "
            f"exit_code={snapshot.exit_code} "
            f"failure={snapshot.failure_message}"
        )

        if snapshot.state is expected:
            return

        if snapshot.state is RuntimeProcessState.FAILED:
            raise RuntimeError(snapshot.failure_message or "runtime failed")

        time.sleep(POLL_INTERVAL_SECONDS)

    raise TimeoutError(f"runtime did not reach {expected.value}")


def run_once(
    host: RuntimeProcessHost,
) -> None:
    snapshot = host.start()

    print(f"start requested state={snapshot.state.value} pid={snapshot.pid}")

    wait_for_state(
        host,
        expected=RuntimeProcessState.RUNNING,
        timeout_seconds=START_TIMEOUT_SECONDS,
    )

    print("runtime is running")
    input("Press Enter to request graceful stop...")

    snapshot = host.stop()

    print(f"stop requested state={snapshot.state.value} pid={snapshot.pid}")

    wait_for_state(
        host,
        expected=RuntimeProcessState.STOPPED,
        timeout_seconds=STOP_TIMEOUT_SECONDS,
    )

    print("runtime stopped cleanly")


def main() -> None:
    host = RuntimeProcessHost(
        runtime_paths=create_development_runtime_paths(),
        session_factory=MultiprocessingRuntimeProcessSessionFactory(),
    )

    print("=== Runtime 1 ===")
    run_once(host)

    print()
    print("=== Runtime 2 ===")
    run_once(host)

    print()
    print("Start → Stop → Start → Stop succeeded.")


if __name__ == "__main__":
    main()
