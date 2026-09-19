from __future__ import annotations

import json
import subprocess
from collections.abc import Sequence
from typing import Protocol

from app.observability.hardware import (
    GraphicsAdapterInfo,
    GraphicsAdaptersObservation,
)

_DEFAULT_TIMEOUT_SECONDS = 5.0
_MAX_ERROR_LENGTH = 1000

_POWERSHELL_QUERY = """
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

Get-CimInstance -ClassName Win32_VideoController |
    Select-Object -Property Name, DriverVersion, PNPDeviceID |
    ConvertTo-Json -Compress
""".strip()


class _CommandRunner(Protocol):
    def __call__(
        self,
        command: Sequence[str],
        *,
        timeout_seconds: float,
    ) -> subprocess.CompletedProcess[str]:
        """Run one bounded operating-system command."""


class _GraphicsAdapterParsingError(Exception):
    """Windows graphics-adapter output could not be parsed."""


def _run_command(
    command: Sequence[str],
    *,
    timeout_seconds: float,
) -> subprocess.CompletedProcess[str]:
    creation_flags = getattr(
        subprocess,
        "CREATE_NO_WINDOW",
        0,
    )

    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout_seconds,
        check=False,
        creationflags=creation_flags,
    )


class WindowsVideoControllerObserver:
    """Observe Windows graphics adapters through CIM."""

    def __init__(
        self,
        *,
        command_runner: _CommandRunner = _run_command,
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")

        self._command_runner = command_runner
        self._timeout_seconds = timeout_seconds

    def observe(self) -> GraphicsAdaptersObservation:
        command = (
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            _POWERSHELL_QUERY,
        )

        try:
            result = self._command_runner(
                command,
                timeout_seconds=self._timeout_seconds,
            )

        except subprocess.TimeoutExpired:
            return GraphicsAdaptersObservation.failure(
                error_type="TimeoutExpired",
                error=(
                    "Windows graphics adapter query timed out "
                    f"after {self._timeout_seconds:g} seconds."
                ),
            )

        except OSError as exc:
            return GraphicsAdaptersObservation.failure(
                error_type=type(exc).__name__,
                error=_bounded_error(str(exc)),
            )

        except Exception as exc:
            return GraphicsAdaptersObservation.failure(
                error_type=type(exc).__name__,
                error=_bounded_error(str(exc)),
            )

        if result.returncode != 0:
            detail = (
                result.stderr.strip()
                or result.stdout.strip()
                or (f"PowerShell exited with code {result.returncode}.")
            )

            return GraphicsAdaptersObservation.failure(
                error_type="PowerShellCommandError",
                error=_bounded_error(detail),
            )

        try:
            adapters = _parse_adapters(
                result.stdout,
            )

        except _GraphicsAdapterParsingError as exc:
            return GraphicsAdaptersObservation.failure(
                error_type=type(exc).__name__,
                error=_bounded_error(str(exc)),
            )

        return GraphicsAdaptersObservation.success(
            adapters,
        )


def _parse_adapters(
    value: str,
) -> tuple[GraphicsAdapterInfo, ...]:
    value = value.strip()

    if not value:
        return ()

    try:
        document: object = json.loads(value)
    except json.JSONDecodeError as exc:
        raise _GraphicsAdapterParsingError(
            "Windows graphics adapter query returned invalid JSON."
        ) from exc

    if isinstance(document, dict):
        rows: list[object] = [
            document,
        ]

    elif isinstance(document, list):
        rows = document

    else:
        raise _GraphicsAdapterParsingError(
            "Windows graphics adapter query returned an unexpected JSON value."
        )

    adapters = tuple(
        _parse_adapter(
            row,
            index=index,
        )
        for index, row in enumerate(rows)
    )

    return tuple(
        sorted(
            adapters,
            key=lambda adapter: (
                adapter.name.casefold(),
                adapter.pnp_device_id or "",
                adapter.driver_version or "",
            ),
        )
    )


def _parse_adapter(
    value: object,
    *,
    index: int,
) -> GraphicsAdapterInfo:
    if not isinstance(value, dict):
        raise _GraphicsAdapterParsingError(
            f"Windows graphics adapter entry {index} must be an object."
        )

    name = _require_string(
        value.get("Name"),
        field=f"adapter[{index}].Name",
    )

    driver_version = _optional_string(
        value.get("DriverVersion"),
        field=f"adapter[{index}].DriverVersion",
    )

    pnp_device_id = _optional_string(
        value.get("PNPDeviceID"),
        field=f"adapter[{index}].PNPDeviceID",
    )

    return GraphicsAdapterInfo(
        name=name,
        driver_version=driver_version,
        pnp_device_id=pnp_device_id,
    )


def _require_string(
    value: object,
    *,
    field: str,
) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _GraphicsAdapterParsingError(f"{field} must be a non-empty string.")

    return value.strip()


def _optional_string(
    value: object,
    *,
    field: str,
) -> str | None:
    if value is None:
        return None

    if not isinstance(value, str):
        raise _GraphicsAdapterParsingError(f"{field} must be a string or null.")

    value = value.strip()

    return value or None


def _bounded_error(
    value: str,
) -> str:
    value = " ".join(value.split())

    if not value:
        return "Unknown graphics-adapter observation error."

    return value[:_MAX_ERROR_LENGTH]
