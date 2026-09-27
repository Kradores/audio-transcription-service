from __future__ import annotations

import sys
from pathlib import Path


def _is_platform_path(
    path: Path,
    platform: str,
) -> bool:
    parts = path.parts

    return any(
        parts[index : index + 2] == ("platforms", platform) for index in range(len(parts) - 1)
    )


def pytest_ignore_collect(
    collection_path: Path,
) -> bool | None:
    """Exclude platform-specific tests before importing their modules."""

    if sys.platform == "win32":
        if _is_platform_path(collection_path, "linux"):
            return True

        return None

    if sys.platform.startswith("linux"):
        if _is_platform_path(collection_path, "windows"):
            return True

        return None

    if _is_platform_path(collection_path, "windows") or _is_platform_path(collection_path, "linux"):
        return True

    return None
