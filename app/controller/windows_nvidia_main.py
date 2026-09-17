from __future__ import annotations

import multiprocessing
import sys
from pathlib import Path

from app.core.runtime_paths import (
    create_installed_windows_runtime_paths,
)


def get_packaged_nvidia_runtime_directory() -> Path:
    """Return the NVIDIA runtime directory bundled by PyInstaller."""

    bundle_directory = getattr(
        sys,
        "_MEIPASS",
        None,
    )

    if not isinstance(bundle_directory, str):
        raise RuntimeError("NVIDIA packaged runtime directory is unavailable")

    return (Path(bundle_directory) / "nvidia-runtime").resolve()


def main() -> None:
    """Run the packaged NVIDIA Windows controller."""

    multiprocessing.freeze_support()

    # Import only after freeze_support so spawned runtime
    # children are handled before controller composition.
    from app.controller.main import run_controller

    run_controller(
        create_installed_windows_runtime_paths(),
        nvidia_runtime_directory=(get_packaged_nvidia_runtime_directory()),
    )


if __name__ == "__main__":
    main()
