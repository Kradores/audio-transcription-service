from __future__ import annotations

from pathlib import Path

from app.core.config.models import LoggingSettings
from app.core.logging import configure_logging


def derive_controller_log_path(
    runtime_log_path: Path,
) -> Path:
    """Derive the controller-owned sibling log path."""

    return runtime_log_path.with_name(
        f"{runtime_log_path.stem}.controller{runtime_log_path.suffix}"
    )


def configure_controller_logging(
    settings: LoggingSettings,
) -> Path | None:
    """Configure logging owned by the controller process."""

    controller_log_path: Path | None = None

    if settings.file.enabled:
        controller_log_path = derive_controller_log_path(settings.file.path)

    configure_logging(
        settings,
        file_path=controller_log_path,
    )

    return controller_log_path
