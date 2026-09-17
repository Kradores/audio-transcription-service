from __future__ import annotations

import multiprocessing
import tkinter as tk
from pathlib import Path

from app.controller.multiprocessing_runtime import (
    MultiprocessingRuntimeProcessSessionFactory,
)
from app.controller.runtime_process import RuntimeProcessHost
from app.controller.shell import WindowsShellOpener
from app.controller.support_bundle import (
    ConfigurationSupportArtifactPathResolver,
    DefaultSupportInfoCollector,
    SupportBundleBuilder,
)
from app.controller.window import ControllerWindow
from app.core.runtime_paths import (
    RuntimePaths,
    create_development_runtime_paths,
)


def run_controller(
    runtime_paths: RuntimePaths,
    *,
    nvidia_runtime_directory: Path | None = None,
) -> None:
    root = tk.Tk()

    runtime_host = RuntimeProcessHost(
        runtime_paths=runtime_paths,
        session_factory=(
            MultiprocessingRuntimeProcessSessionFactory(
                nvidia_runtime_directory=(nvidia_runtime_directory),
            )
        ),
    )

    shell_opener = WindowsShellOpener()

    support_bundle_creator = SupportBundleBuilder(
        runtime_paths=runtime_paths,
        path_resolver=(ConfigurationSupportArtifactPathResolver(runtime_paths)),
        info_collector=DefaultSupportInfoCollector(runtime_paths),
    )

    ControllerWindow(
        root=root,
        runtime_host=runtime_host,
        runtime_paths=runtime_paths,
        shell_opener=shell_opener,
        support_bundle_creator=(support_bundle_creator),
    )

    root.mainloop()


def main() -> None:
    multiprocessing.freeze_support()

    run_controller(
        create_development_runtime_paths(),
    )


if __name__ == "__main__":
    main()
