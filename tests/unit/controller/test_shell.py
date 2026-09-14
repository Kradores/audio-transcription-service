from collections.abc import Sequence
from pathlib import Path

import pytest

from app.controller.shell import WindowsShellOpener


def test_open_directory_creates_missing_directory(
    tmp_path: Path,
) -> None:
    opened_paths: list[str] = []

    opener = WindowsShellOpener(
        start_file=opened_paths.append,
    )
    logs_directory = tmp_path / "logs"

    opener.open_directory(
        logs_directory,
    )

    assert logs_directory.is_dir()
    assert opened_paths == [
        str(logs_directory),
    ]


def test_open_directory_opens_existing_directory(
    tmp_path: Path,
) -> None:
    opened_paths: list[str] = []

    data_directory = tmp_path / "data"
    data_directory.mkdir()

    opener = WindowsShellOpener(
        start_file=opened_paths.append,
    )

    opener.open_directory(
        data_directory,
    )

    assert opened_paths == [
        str(data_directory),
    ]


def test_open_text_file_opens_existing_file_in_notepad(
    tmp_path: Path,
) -> None:
    started_commands: list[Sequence[str]] = []

    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "application:\n  name: test\n",
        encoding="utf-8",
    )

    opener = WindowsShellOpener(
        start_process=started_commands.append,
    )

    opener.open_text_file(
        config_path,
    )

    assert started_commands == [
        (
            "notepad.exe",
            str(config_path),
        )
    ]


def test_open_file_does_not_create_missing_file(
    tmp_path: Path,
) -> None:
    opened_paths: list[str] = []

    config_path = tmp_path / "config.yaml"

    opener = WindowsShellOpener(
        start_file=opened_paths.append,
    )

    with pytest.raises(
        FileNotFoundError,
        match="File does not exist",
    ):
        opener.open_text_file(
            config_path,
        )

    assert not config_path.exists()
    assert opened_paths == []
