from __future__ import annotations

import os
import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Protocol


class ShellOpener(Protocol):
    """Open controller-owned files and directories with Windows."""

    def open_directory(
        self,
        path: Path,
    ) -> None:
        """Open a directory in Windows Explorer."""

    def open_text_file(
        self,
        path: Path,
    ) -> None:
        """Open a text file in the system text editor."""


def _start_file(path: str) -> None:
    os.startfile(path)


def _start_process(
    command: Sequence[str],
) -> None:
    subprocess.Popen(
        command,
        close_fds=True,
    )


class WindowsShellOpener:
    def __init__(
        self,
        start_file: Callable[[str], None] = _start_file,
        start_process: Callable[[Sequence[str]], None] = _start_process,
    ) -> None:
        self._start_file = start_file
        self._start_process = start_process

    def open_directory(
        self,
        path: Path,
    ) -> None:
        path.mkdir(
            parents=True,
            exist_ok=True,
        )

        self._start_file(str(path))

    def open_text_file(
        self,
        path: Path,
    ) -> None:
        if not path.is_file():
            raise FileNotFoundError(f"File does not exist: {path}")

        self._start_process(
            (
                "notepad.exe",
                str(path),
            )
        )
