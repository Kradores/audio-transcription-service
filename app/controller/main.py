from __future__ import annotations

import multiprocessing
import tkinter as tk
from pathlib import Path

from app.controller.distribution_metadata import (
    DevelopmentDistributionMetadataProvider,
    DistributionMetadataProvider,
)
from app.controller.model_provisioning import WhisperModelProvisioningHost
from app.controller.model_status import (
    ConfiguredWhisperModelStatusProvider,
)
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
from app.core.config.loader import ConfigurationLoader
from app.core.runtime_paths import (
    RuntimePaths,
    create_development_runtime_paths,
)
from app.models.whisper import LocalWhisperModelResolver
from app.models.whisper_provisioner import HuggingFaceWhisperModelProvisioner


def run_controller(
    runtime_paths: RuntimePaths,
    *,
    distribution_metadata_provider: DistributionMetadataProvider | None = None,
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

    model_resolver = LocalWhisperModelResolver(
        runtime_paths.models_directory,
    )

    model_status_provider = ConfiguredWhisperModelStatusProvider(
        settings_loader=lambda: ConfigurationLoader(runtime_paths).load(),
        resolver=model_resolver,
    )

    model_provisioning_host = WhisperModelProvisioningHost(
        status_provider=model_status_provider,
        provisioner=HuggingFaceWhisperModelProvisioner(
            resolver=model_resolver,
        ),
    )

    shell_opener = WindowsShellOpener()

    support_bundle_creator = SupportBundleBuilder(
        runtime_paths=runtime_paths,
        path_resolver=ConfigurationSupportArtifactPathResolver(
            runtime_paths,
        ),
        info_collector=DefaultSupportInfoCollector(
            runtime_paths,
            distribution_metadata_provider=(distribution_metadata_provider),
            runtime_diagnostics_provider=(lambda: runtime_host.diagnostics_snapshot),
            whisper_model_diagnostics_provider=(lambda: model_provisioning_host.status),
        ),
    )

    ControllerWindow(
        root=root,
        runtime_host=runtime_host,
        runtime_paths=runtime_paths,
        shell_opener=shell_opener,
        support_bundle_creator=support_bundle_creator,
        model_provisioning_host=model_provisioning_host,
    )

    root.mainloop()


def main() -> None:
    multiprocessing.freeze_support()

    runtime_paths = create_development_runtime_paths()

    run_controller(
        runtime_paths,
        distribution_metadata_provider=(
            DevelopmentDistributionMetadataProvider(
                project_root=(runtime_paths.root_directory),
            )
        ),
    )


if __name__ == "__main__":
    main()
