from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.controller.windows_nvidia_main import (
    get_packaged_nvidia_runtime_directory,
    main,
)


def test_get_packaged_nvidia_runtime_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        sys,
        "_MEIPASS",
        str(tmp_path),
        raising=False,
    )

    result = get_packaged_nvidia_runtime_directory()

    assert result == (tmp_path / "nvidia-runtime").resolve()


@patch("app.controller.windows_nvidia_main.FileDistributionMetadataProvider")
@patch("app.controller.windows_nvidia_main.get_packaged_distribution_metadata_path")
@patch("app.controller.windows_nvidia_main.get_packaged_nvidia_runtime_directory")
@patch("app.controller.windows_nvidia_main.create_installed_windows_runtime_paths")
@patch("app.controller.windows_nvidia_main.multiprocessing.freeze_support")
@patch("app.controller.main.run_controller")
def test_main_runs_controller_with_nvidia_distribution_metadata(
    run_controller: MagicMock,
    freeze_support: MagicMock,
    create_runtime_paths: MagicMock,
    get_nvidia_runtime_directory: MagicMock,
    get_distribution_metadata_path: MagicMock,
    create_distribution_metadata_provider: MagicMock,
) -> None:
    runtime_paths = MagicMock()
    nvidia_runtime_directory = MagicMock()
    metadata_path = MagicMock()
    metadata_provider = MagicMock()

    create_runtime_paths.return_value = runtime_paths

    get_nvidia_runtime_directory.return_value = nvidia_runtime_directory

    get_distribution_metadata_path.return_value = metadata_path

    create_distribution_metadata_provider.return_value = metadata_provider

    main()

    freeze_support.assert_called_once_with()

    create_distribution_metadata_provider.assert_called_once_with(
        metadata_path,
    )

    run_controller.assert_called_once_with(
        runtime_paths,
        distribution_metadata_provider=metadata_provider,
        nvidia_runtime_directory=nvidia_runtime_directory,
    )
