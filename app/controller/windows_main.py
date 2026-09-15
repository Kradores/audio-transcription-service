from __future__ import annotations

import multiprocessing

from app.core.runtime_paths import (
    create_installed_windows_runtime_paths,
)


def main() -> None:
    """Run the packaged Windows controller."""

    multiprocessing.freeze_support()

    # Import after freeze_support so multiprocessing worker startup
    # can be handled before the GUI/controller graph is imported.
    from app.controller.main import run_controller

    run_controller(
        create_installed_windows_runtime_paths(),
    )


if __name__ == "__main__":
    main()
