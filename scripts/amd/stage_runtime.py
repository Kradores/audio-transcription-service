from __future__ import annotations

import argparse
import importlib.metadata
import json
import shutil
from collections.abc import Callable
from pathlib import Path


DistributionFilter = Callable[[Path], bool]

THEROCK_DISTRIBUTIONS = (
    "rocm",
    "rocm-sdk-core",
    "rocm-sdk-devel",
    "rocm-sdk-device-gfx1031",
    "rocm-sdk-libraries",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--source-venv",
        type=Path,
        required=True,
    )

    parser.add_argument(
        "--output",
        type=Path,
        required=True,
    )

    return parser.parse_args()


def load_expected_versions() -> dict[str, str]:
    toolchain_path = (
        Path(__file__).resolve().parent
        / "toolchain.json"
    )

    with toolchain_path.open(
        encoding="utf-8",
    ) as file:
        document = json.load(file)

    return dict(
        document["required"]["therock"]["packages"]
    )


def validate_versions(
    expected_versions: dict[str, str],
) -> None:
    for name in THEROCK_DISTRIBUTIONS:
        actual = importlib.metadata.version(
            name
        )

        expected = expected_versions[name]

        if actual != expected:
            raise RuntimeError(
                "TheRock package version mismatch: "
                f"package={name} "
                f"expected={expected} "
                f"actual={actual}"
            )


def is_dist_info(path: Path) -> bool:
    return (
        len(path.parts) > 0
        and path.parts[0].endswith(
            ".dist-info"
        )
    )


def copy_distribution_files(
    *,
    distribution_name: str,
    site_packages: Path,
    output: Path,
    include: DistributionFilter,
) -> int:
    distribution = (
        importlib.metadata.distribution(
            distribution_name
        )
    )

    copied = 0

    for item in distribution.files or []:
        source = Path(
            distribution.locate_file(
                item
            )
        ).resolve()

        if not source.is_file():
            continue

        try:
            relative = (
                source.relative_to(
                    site_packages
                )
            )
        except ValueError:
            # Ignore Scripts/, executables, etc.
            # The packaged runtime only stages
            # site-packages content here.
            continue

        if not include(relative):
            continue

        destination = (
            output
            / relative
        )

        destination.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        shutil.copy2(
            source,
            destination,
        )

        copied += 1

    return copied


def include_rocm(
    path: Path,
) -> bool:
    return (
        path.parts[0] == "rocm_sdk"
        or is_dist_info(path)
    )


def include_core(
    path: Path,
) -> bool:
    if is_dist_info(path):
        return True

    if path.parts[0] != "_rocm_sdk_core":
        return False

    if len(path.parts) == 2:
        return path.name == "__init__.py"

    return path.parts[1] in {
        ".info",
        "bin",
    }


def include_libraries(
    path: Path,
) -> bool:
    if is_dist_info(path):
        return True

    if path.parts[0] != "_rocm_sdk_libraries":
        return False

    if len(path.parts) == 2:
        return path.name == "__init__.py"

    return path.parts[1] in {
        ".info",
        "bin",
    }


def include_all_site_package_files(
    path: Path,
) -> bool:
    # The gfx1031 wheel is intentionally
    # copied by distribution ownership.
    #
    # It overlays target-specific runtime
    # assets into several ROCm package trees.
    return True


def copy_minimal_devel_package_root(
    *,
    site_packages: Path,
    output: Path,
) -> None:
    source_root = (
        site_packages
        / "_rocm_sdk_devel"
    )

    destination_root = (
        output
        / "_rocm_sdk_devel"
    )

    init_file = (
        source_root
        / "__init__.py"
    )

    if init_file.is_file():
        destination_root.mkdir(
            parents=True,
            exist_ok=True,
        )

        shutil.copy2(
            init_file,
            destination_root
            / "__init__.py",
        )

    info_directory = (
        source_root
        / ".info"
    )

    if info_directory.is_dir():
        shutil.copytree(
            info_directory,
            destination_root / ".info",
            dirs_exist_ok=True,
        )


def calculate_size(path: Path) -> int:
    return sum(
        item.stat().st_size
        for item in path.rglob("*")
        if item.is_file()
    )


def main() -> None:
    args = parse_args()

    source_venv = (
        args.source_venv.resolve()
    )

    site_packages = (
        source_venv
        / "Lib"
        / "site-packages"
    )

    if not site_packages.is_dir():
        raise RuntimeError(
            "Source site-packages does not exist: "
            f"{site_packages}"
        )

    output = args.output.resolve()

    if output.exists():
        shutil.rmtree(output)

    output.mkdir(
        parents=True,
        exist_ok=True,
    )

    validate_versions(
        load_expected_versions()
    )

    copy_distribution_files(
        distribution_name="rocm",
        site_packages=site_packages,
        output=output,
        include=include_rocm,
    )

    copy_distribution_files(
        distribution_name="rocm-sdk-core",
        site_packages=site_packages,
        output=output,
        include=include_core,
    )

    copy_distribution_files(
        distribution_name="rocm-sdk-libraries",
        site_packages=site_packages,
        output=output,
        include=include_libraries,
    )

    # Important:
    # copy every site-packages file owned by
    # the gfx1031 device distribution.
    #
    # This captures .kpack, HSACO, DAT, and
    # other target-specific runtime assets
    # regardless of which ROCm tree they
    # were installed into.
    copy_distribution_files(
        distribution_name=(
            "rocm-sdk-device-gfx1031"
        ),
        site_packages=site_packages,
        output=output,
        include=include_all_site_package_files,
    )

    copy_minimal_devel_package_root(
        site_packages=site_packages,
        output=output,
    )

    size = calculate_size(output)

    print(
        "AMD runtime staged successfully.",
        flush=True,
    )
    print(
        f"Output: {output}",
        flush=True,
    )
    print(
        f"Size: {size / (1024 * 1024):.1f} MB",
        flush=True,
    )


if __name__ == "__main__":
    main()