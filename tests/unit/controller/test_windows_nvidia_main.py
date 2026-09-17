from __future__ import annotations

import sys
from pathlib import Path

import pytest

from app.controller.windows_nvidia_main import (
    get_packaged_nvidia_runtime_directory,
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
