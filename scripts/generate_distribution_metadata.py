from __future__ import annotations

import argparse
import json
import tomllib
from collections.abc import Callable
from importlib import metadata
from pathlib import Path

from app.controller.distribution_metadata import (
    APPLICATION_PACKAGE_NAME,
    DEFAULT_DISTRIBUTION_PACKAGE_NAMES,
    DISTRIBUTION_METADATA_SCHEMA_VERSION,
    DistributionMetadata,
    DistributionProfile,
    DistributionRuntimeKind,
    DistributionRuntimeMetadata,
)

type PackageVersionResolver = Callable[[str], str]

_NVIDIA_COMPONENT_PACKAGES = {
    "cublas": "nvidia-cublas-cu12",
    "cudnn": "nvidia-cudnn-cu12",
    "nvrtc": "nvidia-cuda-nvrtc-cu12",
}


class DistributionMetadataGenerationError(Exception):
    """Raised when deterministic distribution metadata cannot be generated."""


def create_distribution_metadata(
    *,
    profile: DistributionProfile,
    project_root: Path,
    version_resolver: PackageVersionResolver = metadata.version,
    nvidia_runtime_manifest_path: Path | None = None,
) -> DistributionMetadata:
    application_version = _load_application_version(
        project_root / "pyproject.toml",
    )

    packages = _collect_package_versions(
        application_version=application_version,
        version_resolver=version_resolver,
    )

    if profile is DistributionProfile.CPU:
        runtime = DistributionRuntimeMetadata(
            kind=DistributionRuntimeKind.DEFAULT,
            components=(),
        )

    elif profile is DistributionProfile.NVIDIA:
        if nvidia_runtime_manifest_path is None:
            raise DistributionMetadataGenerationError(
                "NVIDIA runtime manifest path is required for the NVIDIA distribution"
            )

        runtime = _create_nvidia_runtime_metadata(
            project_root=project_root,
            package_versions=dict(packages),
            runtime_manifest_path=nvidia_runtime_manifest_path,
        )

    else:
        raise DistributionMetadataGenerationError(
            f"Distribution metadata generation is not implemented for profile={profile.value!r}"
        )

    return DistributionMetadata(
        schema_version=DISTRIBUTION_METADATA_SCHEMA_VERSION,
        profile=profile,
        application_version=application_version,
        packages=packages,
        runtime=runtime,
    )


def write_distribution_metadata(
    *,
    value: DistributionMetadata,
    output_path: Path,
) -> None:
    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_path.write_text(
        json.dumps(
            value.to_dict(),
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _collect_package_versions(
    *,
    application_version: str,
    version_resolver: PackageVersionResolver,
) -> tuple[tuple[str, str], ...]:
    result: list[tuple[str, str]] = []

    for package_name in DEFAULT_DISTRIBUTION_PACKAGE_NAMES:
        if package_name == APPLICATION_PACKAGE_NAME:
            version = application_version
        else:
            try:
                version = version_resolver(package_name)
            except metadata.PackageNotFoundError as exc:
                raise DistributionMetadataGenerationError(
                    f"Required distribution package metadata is unavailable: {package_name}"
                ) from exc

        if not version.strip():
            raise DistributionMetadataGenerationError(f"Package version is empty: {package_name}")

        result.append(
            (
                package_name,
                version,
            )
        )

    return tuple(
        sorted(result),
    )


def _create_nvidia_runtime_metadata(
    *,
    project_root: Path,
    package_versions: dict[str, str],
    runtime_manifest_path: Path,
) -> DistributionRuntimeMetadata:
    runtime_manifest = _load_json_object(
        runtime_manifest_path,
    )

    toolchain = _load_json_object(
        project_root / "scripts" / "nvidia" / "toolchain.json",
    )

    manifest_packages = _require_object(
        runtime_manifest.get("packages"),
        field="NVIDIA runtime manifest packages",
    )

    toolchain_runtime = _require_object(
        toolchain.get("runtime"),
        field="NVIDIA toolchain runtime",
    )

    toolchain_nvidia = _require_object(
        toolchain.get("nvidia"),
        field="NVIDIA toolchain nvidia",
    )

    toolchain_packages = _require_object(
        toolchain_nvidia.get("packages"),
        field="NVIDIA toolchain packages",
    )

    _validate_python_runtime_version(
        package_versions=package_versions,
        package_name="faster-whisper",
        expected=_require_string(
            toolchain_runtime.get("faster_whisper"),
            field="toolchain runtime faster_whisper",
        ),
    )

    _validate_python_runtime_version(
        package_versions=package_versions,
        package_name="ctranslate2",
        expected=_require_string(
            toolchain_runtime.get("ctranslate2"),
            field="toolchain runtime ctranslate2",
        ),
    )

    components: list[tuple[str, str]] = []

    for component_name, package_name in _NVIDIA_COMPONENT_PACKAGES.items():
        manifest_version = _require_string(
            manifest_packages.get(package_name),
            field=f"NVIDIA runtime package {package_name}",
        )

        expected_version = _require_string(
            toolchain_packages.get(package_name),
            field=f"NVIDIA toolchain package {package_name}",
        )

        if manifest_version != expected_version:
            raise DistributionMetadataGenerationError(
                "Prepared NVIDIA runtime does not match toolchain "
                f"package={package_name!r} "
                f"expected={expected_version!r} "
                f"actual={manifest_version!r}"
            )

        components.append(
            (
                component_name,
                manifest_version,
            )
        )

    return DistributionRuntimeMetadata(
        kind=DistributionRuntimeKind.NVIDIA,
        components=tuple(
            sorted(components),
        ),
    )


def _validate_python_runtime_version(
    *,
    package_versions: dict[str, str],
    package_name: str,
    expected: str,
) -> None:
    actual = package_versions.get(package_name)

    if actual != expected:
        raise DistributionMetadataGenerationError(
            "Python runtime package does not match NVIDIA toolchain "
            f"package={package_name!r} "
            f"expected={expected!r} "
            f"actual={actual!r}"
        )


def _load_application_version(
    path: Path,
) -> str:
    with path.open(
        "rb",
    ) as file:
        document = tomllib.load(file)

    project = document.get("project")

    if not isinstance(project, dict):
        raise DistributionMetadataGenerationError("pyproject.toml does not contain a project table")

    version = project.get("version")

    if not isinstance(version, str) or not version.strip():
        raise DistributionMetadataGenerationError("pyproject.toml project.version is unavailable")

    return version


def _load_json_object(
    path: Path,
) -> dict[str, object]:
    try:
        with path.open(
            "r",
            encoding="utf-8",
        ) as file:
            value: object = json.load(file)
    except (OSError, json.JSONDecodeError) as exc:
        raise DistributionMetadataGenerationError(f"Could not load JSON metadata: {path}") from exc

    return _require_object(
        value,
        field=str(path),
    )


def _require_object(
    value: object,
    *,
    field: str,
) -> dict[str, object]:
    if not isinstance(value, dict):
        raise DistributionMetadataGenerationError(f"{field} must be an object")

    result: dict[str, object] = {}

    for key, item in value.items():
        if not isinstance(key, str):
            raise DistributionMetadataGenerationError(f"{field} contains a non-string key")

        result[key] = item

    return result


def _require_string(
    value: object,
    *,
    field: str,
) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DistributionMetadataGenerationError(f"{field} must be a non-empty string")

    return value


def main() -> None:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--profile",
        required=True,
        choices=(
            DistributionProfile.CPU.value,
            DistributionProfile.NVIDIA.value,
        ),
    )

    parser.add_argument(
        "--project-root",
        required=True,
        type=Path,
    )

    parser.add_argument(
        "--output",
        required=True,
        type=Path,
    )

    parser.add_argument(
        "--nvidia-runtime-manifest",
        type=Path,
    )

    arguments = parser.parse_args()

    value = create_distribution_metadata(
        profile=DistributionProfile(arguments.profile),
        project_root=arguments.project_root.resolve(),
        nvidia_runtime_manifest_path=(
            arguments.nvidia_runtime_manifest.resolve()
            if arguments.nvidia_runtime_manifest is not None
            else None
        ),
    )

    write_distribution_metadata(
        value=value,
        output_path=arguments.output.resolve(),
    )


if __name__ == "__main__":
    main()
