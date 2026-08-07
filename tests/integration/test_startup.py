from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_application_module_starts_successfully() -> None:
    # Arrange

    # Act
    result = subprocess.run(
        [sys.executable, "-m", "app"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    # Assert
    assert result.returncode == 0
    assert "Application started successfully" in result.stderr
