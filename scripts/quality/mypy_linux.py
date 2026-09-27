from __future__ import annotations

import subprocess
import sys


def main() -> int:
    command = [
        sys.executable,
        "-m",
        "mypy",
        ".",
        "--exclude",
        r"(^|/)app/platforms/windows/",
        "--exclude",
        r"(^|/)tests/(unit|integration)/platforms/windows/",
        "--exclude",
        r"(^|/)scripts/(amd|nvidia)/",
    ]

    return subprocess.run(
        command,
        check=False,
    ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
