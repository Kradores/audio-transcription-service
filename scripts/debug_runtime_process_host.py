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


def print_graphics_diagnostics(
    host: RuntimeProcessHost,
) -> None:
    observation = host.diagnostics_snapshot.graphics_adapters

    if observation is None:
        print("graphics diagnostics: not observed")
        return

    if not observation.available:
        print(
            "graphics diagnostics: unavailable "
            f"error_type={observation.error_type} "
            f"error={observation.error}"
        )
        return

    print(f"graphics diagnostics: adapters={len(observation.adapters)}")

    for adapter in observation.adapters:
        print(
            "  "
            f"name={adapter.name!r} "
            f"driver_version={adapter.driver_version!r} "
            f"pnp_device_id={adapter.pnp_device_id!r}"
        )


def run_once(
    host: RuntimeProcessHost,
) -> None:
    snapshot = host.start()

    print(f"start requested state={snapshot.state.value} pid={snapshot.pid}")

    try:
        wait_for_state(
            host,
            expected=RuntimeProcessState.RUNNING,
            timeout_seconds=START_TIMEOUT_SECONDS,
        )
    except RuntimeError:
        print("graphics diagnostics after startup failure:")
        print_graphics_diagnostics(host)
        raise

    print("runtime is running")

    print_graphics_diagnostics(host)

    wait_for_transcription_diagnostics(
        host,
        timeout_seconds=5.0,
    )

    print_transcription_diagnostics(host)

    input("Press Enter to request graceful stop...")

    snapshot = host.stop()

    print(f"stop requested state={snapshot.state.value} pid={snapshot.pid}")

    wait_for_state(
        host,
        expected=RuntimeProcessState.STOPPED,
        timeout_seconds=STOP_TIMEOUT_SECONDS,
    )

    print("runtime stopped cleanly")

    print("graphics diagnostics after stop:")
    print_graphics_diagnostics(host)

    print("transcription diagnostics after stop:")
    print_transcription_diagnostics(host)


def wait_for_transcription_diagnostics(
    host: RuntimeProcessHost,
    *,
    timeout_seconds: float,
) -> None:
    deadline = time.monotonic() + timeout_seconds

    while time.monotonic() < deadline:
        host.refresh()

        if host.diagnostics_snapshot.transcription_runtime is not None:
            return

        time.sleep(POLL_INTERVAL_SECONDS)

    raise TimeoutError("timed out waiting for transcription runtime diagnostics")


def print_transcription_diagnostics(
    host: RuntimeProcessHost,
) -> None:
    observation = host.diagnostics_snapshot.transcription_runtime

    if observation is None:
        print("transcription diagnostics: not observed")
        return

    capabilities = observation.ctranslate2

    print(
        "transcription diagnostics: "
        f"runtime={observation.runtime.value!r} "
        f"device={observation.device.value!r} "
        f"compute_type="
        f"{observation.configured_compute_type.value!r} "
        f"initialized={observation.initialized}"
    )

    if not capabilities.available:
        print(
            "  ctranslate2: unavailable "
            f"error_type={capabilities.error_type!r} "
            f"error={capabilities.error!r}"
        )
        return

    print(f"  ctranslate2: cuda_device_count={capabilities.cuda_device_count!r}")

    print(f"  supported_compute_types={list(capabilities.supported_compute_types)!r}")


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
