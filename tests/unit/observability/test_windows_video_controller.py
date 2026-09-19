from __future__ import annotations

import subprocess
from collections.abc import Sequence

from app.observability.windows_video_controller import (
    WindowsVideoControllerObserver,
)


class StubCommandRunner:
    def __init__(
        self,
        *,
        returncode: int = 0,
        stdout: str = "",
        stderr: str = "",
    ) -> None:
        self._result = subprocess.CompletedProcess(
            args=(),
            returncode=returncode,
            stdout=stdout,
            stderr=stderr,
        )

        self.commands: list[Sequence[str]] = []
        self.timeouts: list[float] = []

    def __call__(
        self,
        command: Sequence[str],
        *,
        timeout_seconds: float,
    ) -> subprocess.CompletedProcess[str]:
        self.commands.append(command)
        self.timeouts.append(timeout_seconds)

        return self._result


def test_observes_one_graphics_adapter() -> None:
    runner = StubCommandRunner(
        stdout=(
            "{"
            '"Name":"AMD Radeon RX 6800M",'
            '"DriverVersion":"32.0.21025.1024",'
            '"PNPDeviceID":"PCI\\\\VEN_1002&DEV_73DF"'
            "}"
        ),
    )

    result = WindowsVideoControllerObserver(
        command_runner=runner,
    ).observe()

    assert result.available is True
    assert len(result.adapters) == 1

    adapter = result.adapters[0]

    assert adapter.name == "AMD Radeon RX 6800M"
    assert adapter.driver_version == "32.0.21025.1024"
    assert adapter.pnp_device_id == ("PCI\\VEN_1002&DEV_73DF")

    assert runner.timeouts == [
        5.0,
    ]

    assert "Get-CimInstance" in runner.commands[0][-1]
    assert "Win32_VideoController" in runner.commands[0][-1]


def test_observes_multiple_adapters_deterministically() -> None:
    runner = StubCommandRunner(
        stdout="""
[
  {
    "Name": "NVIDIA GeForce RTX 2080",
    "DriverVersion": "32.0.15.6094",
    "PNPDeviceID": "PCI\\\\VEN_10DE"
  },
  {
    "Name": "Intel UHD Graphics",
    "DriverVersion": "31.0.101.5590",
    "PNPDeviceID": "PCI\\\\VEN_8086"
  }
]
""",
    )

    result = WindowsVideoControllerObserver(
        command_runner=runner,
    ).observe()

    assert result.available is True

    assert [adapter.name for adapter in result.adapters] == [
        "Intel UHD Graphics",
        "NVIDIA GeForce RTX 2080",
    ]


def test_successful_empty_query_returns_empty_observation() -> None:
    runner = StubCommandRunner(
        stdout="",
    )

    result = WindowsVideoControllerObserver(
        command_runner=runner,
    ).observe()

    assert result.available is True
    assert result.adapters == ()


def test_optional_adapter_fields_may_be_missing() -> None:
    runner = StubCommandRunner(
        stdout="""
{
  "Name": "Microsoft Basic Display Adapter",
  "DriverVersion": null,
  "PNPDeviceID": null
}
""",
    )

    result = WindowsVideoControllerObserver(
        command_runner=runner,
    ).observe()

    assert result.available is True

    adapter = result.adapters[0]

    assert adapter.driver_version is None
    assert adapter.pnp_device_id is None


def test_nonzero_powershell_exit_is_unavailable() -> None:
    runner = StubCommandRunner(
        returncode=1,
        stderr="Get-CimInstance failed",
    )

    result = WindowsVideoControllerObserver(
        command_runner=runner,
    ).observe()

    assert result.available is False
    assert result.adapters == ()
    assert result.error_type == "PowerShellCommandError"
    assert result.error == "Get-CimInstance failed"


def test_invalid_json_is_unavailable() -> None:
    runner = StubCommandRunner(
        stdout="{not-json",
    )

    result = WindowsVideoControllerObserver(
        command_runner=runner,
    ).observe()

    assert result.available is False
    assert result.adapters == ()
    assert result.error_type == ("_GraphicsAdapterParsingError")


def test_timeout_is_unavailable() -> None:
    class TimeoutRunner:
        def __call__(
            self,
            command: Sequence[str],
            *,
            timeout_seconds: float,
        ) -> subprocess.CompletedProcess[str]:
            raise subprocess.TimeoutExpired(
                cmd=command,
                timeout=timeout_seconds,
            )

    result = WindowsVideoControllerObserver(
        command_runner=TimeoutRunner(),
        timeout_seconds=2.0,
    ).observe()

    assert result.available is False
    assert result.error_type == "TimeoutExpired"

    assert result.error is not None
    assert "2 seconds" in result.error


def test_unexpected_command_error_is_unavailable() -> None:
    class FailingRunner:
        def __call__(
            self,
            command: Sequence[str],
            *,
            timeout_seconds: float,
        ) -> subprocess.CompletedProcess[str]:
            del command
            del timeout_seconds

            raise RuntimeError(
                "unexpected diagnostic failure",
            )

    result = WindowsVideoControllerObserver(
        command_runner=FailingRunner(),
    ).observe()

    assert result.available is False
    assert result.adapters == ()
    assert result.error_type == "RuntimeError"
    assert result.error == ("unexpected diagnostic failure")
