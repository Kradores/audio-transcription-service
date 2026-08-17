from __future__ import annotations

import signal
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
STARTUP_TIMEOUT_SECONDS = 30.0


def test_application_module_starts_and_remains_running() -> None:
    # Arrange
    process = subprocess.Popen(
        [sys.executable, "-m", "app"],
        cwd=PROJECT_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
    )

    try:
        # Act
        assert process.stderr is not None

        deadline = time.monotonic() + STARTUP_TIMEOUT_SECONDS
        stderr_lines: list[str] = []

        while time.monotonic() < deadline:
            line = process.stderr.readline()

            if line:
                stderr_lines.append(line)

                if "Application started successfully" in line:
                    break

            if process.poll() is not None:
                break
        else:
            raise AssertionError(
                "Application did not report successful startup within "
                f"{STARTUP_TIMEOUT_SECONDS} seconds.\n"
                f"stderr:\n{''.join(stderr_lines)}"
            )

        # The important regression check:
        # successful startup must leave the application running.
        assert process.poll() is None, (
            "Application exited immediately after startup.\n"
            f"stderr:\n{''.join(stderr_lines)}"
        )

        # Request graceful shutdown.
        process.send_signal(signal.CTRL_BREAK_EVENT)

    finally:
        if process.poll() is None:
            process.kill()
            process.wait()