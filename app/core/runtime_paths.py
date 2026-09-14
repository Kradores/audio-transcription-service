from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

APPLICATION_DATA_DIRECTORY_NAME = "AudioTranscriptionService"


@dataclass(frozen=True, slots=True)
class RuntimePaths:
    """Resolved filesystem locations for one application runtime."""

    root_directory: Path
    config_path: Path
    data_directory: Path
    logs_directory: Path
    diagnostics_directory: Path
    support_directory: Path

    def resolve(self, path: Path) -> Path:
        """Resolve a configured path against the runtime root."""

        if path.is_absolute():
            return path.resolve()

        return (self.root_directory / path).resolve()


def create_development_runtime_paths(
    project_root: Path | None = None,
    *,
    config_path: Path | None = None,
) -> RuntimePaths:
    """Create deterministic paths for source-checkout development."""

    root_directory = (project_root or Path(__file__).resolve().parents[2]).resolve()

    resolved_config_path = config_path or Path("config/config.yaml")

    if not resolved_config_path.is_absolute():
        resolved_config_path = root_directory / resolved_config_path

    return _create_runtime_paths(
        root_directory=root_directory,
        config_path=resolved_config_path.resolve(),
    )


def create_installed_windows_runtime_paths(
    local_app_data: Path | None = None,
) -> RuntimePaths:
    """Create per-user Windows paths below LOCALAPPDATA."""

    base_directory = local_app_data

    if base_directory is None:
        local_app_data_value = os.environ.get("LOCALAPPDATA")

        if not local_app_data_value:
            raise RuntimeError("LOCALAPPDATA is required for installed Windows execution")

        base_directory = Path(local_app_data_value)

    if not base_directory.is_absolute():
        raise ValueError("LOCALAPPDATA path must be absolute")

    root_directory = (base_directory / APPLICATION_DATA_DIRECTORY_NAME).resolve()

    return _create_runtime_paths(
        root_directory=root_directory,
        config_path=root_directory / "config" / "config.yaml",
    )


def _create_runtime_paths(
    *,
    root_directory: Path,
    config_path: Path,
) -> RuntimePaths:
    return RuntimePaths(
        root_directory=root_directory,
        config_path=config_path,
        data_directory=root_directory / "data",
        logs_directory=root_directory / "logs",
        diagnostics_directory=root_directory / "diagnostics",
        support_directory=root_directory / "support",
    )
