from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def write_configuration(
    directory: Path,
    document: dict[str, Any],
    filename: str = "config.yaml",
) -> Path:
    """Write a configuration document to a YAML file."""

    path = directory / filename

    with path.open("w", encoding="utf-8") as file:
        yaml.safe_dump(
            document,
            file,
            sort_keys=False,
        )

    return path
