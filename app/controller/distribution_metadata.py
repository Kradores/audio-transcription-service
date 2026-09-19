from __future__ import annotations

import json
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from importlib import metadata
from pathlib import Path
from typing import Protocol

DISTRIBUTION_METADATA_SCHEMA_VERSION = 1
APPLICATION_PACKAGE_NAME = "audio-transcription-service"

DEFAULT_DISTRIBUTION_PACKAGE_NAMES = (
    APPLICATION_PACKAGE_NAME,
    "faster-whisper",
    "ctranslate2",
    "torch",
    "pyaudiowpatch",
    "pycaw",
    "silero-vad",
    "soxr",
)


class DistributionMetadataError(Exception):
    """Raised when distribution metadata cannot be loaded or validated."""


class DistributionProfile(StrEnum):
    DEVELOPMENT = "development"
    CPU = "cpu"
    NVIDIA = "nvidia"
    AMD = "amd"


class DistributionRuntimeKind(StrEnum):
    DEFAULT = "default"
    NVIDIA = "nvidia"
    THEROCK = "therock"


type VersionEntries = tuple[tuple[str, str], ...]
type PackageVersionResolver = Callable[[str], str]


@dataclass(frozen=True, slots=True)
class DistributionRuntimeMetadata:
    kind: DistributionRuntimeKind
    components: VersionEntries

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind.value,
            "components": dict(self.components),
        }


@dataclass(frozen=True, slots=True)
class DistributionMetadata:
    schema_version: int
    profile: DistributionProfile
    application_version: str
    packages: VersionEntries
    runtime: DistributionRuntimeMetadata | None

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "profile": self.profile.value,
            "application_version": self.application_version,
            "packages": dict(self.packages),
            "runtime": (self.runtime.to_dict() if self.runtime is not None else None),
        }


class DistributionMetadataProvider(Protocol):
    def load(self) -> DistributionMetadata:
        """Load deterministic metadata describing this distribution."""


class FileDistributionMetadataProvider:
    """Load deterministic distribution metadata from a JSON manifest."""

    def __init__(
        self,
        path: Path,
    ) -> None:
        self._path = path

    def load(self) -> DistributionMetadata:
        try:
            with self._path.open(
                "r",
                encoding="utf-8",
            ) as file:
                document: object = json.load(file)
        except (OSError, json.JSONDecodeError) as exc:
            raise DistributionMetadataError(
                f"Could not load distribution metadata: {self._path}"
            ) from exc

        return _parse_distribution_metadata(
            document,
        )


class DevelopmentDistributionMetadataProvider:
    """Describe the current source/development Python environment."""

    def __init__(
        self,
        *,
        project_root: Path,
        package_names: tuple[str, ...] = (DEFAULT_DISTRIBUTION_PACKAGE_NAMES),
        version_resolver: PackageVersionResolver = (metadata.version),
    ) -> None:
        self._project_root = project_root
        self._package_names = package_names
        self._version_resolver = version_resolver

    def load(self) -> DistributionMetadata:
        application_version = _load_project_application_version(
            self._project_root,
        )

        packages: list[tuple[str, str]] = []

        for package_name in self._package_names:
            if package_name == APPLICATION_PACKAGE_NAME:
                packages.append(
                    (
                        package_name,
                        application_version,
                    )
                )
                continue

            try:
                version = self._version_resolver(
                    package_name,
                )
            except metadata.PackageNotFoundError:
                continue

            packages.append(
                (
                    package_name,
                    version,
                )
            )

        return DistributionMetadata(
            schema_version=(DISTRIBUTION_METADATA_SCHEMA_VERSION),
            profile=DistributionProfile.DEVELOPMENT,
            application_version=application_version,
            packages=tuple(
                sorted(packages),
            ),
            runtime=None,
        )


def _load_project_application_version(
    project_root: Path,
) -> str:
    path = project_root / "pyproject.toml"

    try:
        with path.open(
            "rb",
        ) as file:
            document = tomllib.load(file)

    except (
        OSError,
        tomllib.TOMLDecodeError,
    ) as exc:
        raise DistributionMetadataError(
            f"Could not load development project metadata from {path}"
        ) from exc

    project = document.get(
        "project",
    )

    if not isinstance(project, dict):
        raise DistributionMetadataError("pyproject.toml does not contain a project table")

    version = project.get(
        "version",
    )

    if not isinstance(version, str) or not version.strip():
        raise DistributionMetadataError("pyproject.toml project.version is unavailable")

    return version.strip()


def _parse_distribution_metadata(
    value: object,
) -> DistributionMetadata:
    document = _require_object(
        value,
        field="distribution metadata",
    )

    _require_exact_keys(
        document,
        field="distribution metadata",
        expected={
            "schema_version",
            "profile",
            "application_version",
            "packages",
            "runtime",
        },
    )

    schema_version = document["schema_version"]

    if type(schema_version) is not int:
        raise DistributionMetadataError("distribution metadata.schema_version must be an integer")

    if schema_version != DISTRIBUTION_METADATA_SCHEMA_VERSION:
        raise DistributionMetadataError(
            f"Unsupported distribution metadata schema version: {schema_version}"
        )

    profile_value = _require_non_empty_string(
        document["profile"],
        field="distribution metadata.profile",
    )

    try:
        profile = DistributionProfile(
            profile_value,
        )
    except ValueError as exc:
        raise DistributionMetadataError(
            f"Unsupported distribution profile: {profile_value!r}"
        ) from exc

    application_version = _require_non_empty_string(
        document["application_version"],
        field="distribution metadata.application_version",
    )

    packages = _parse_version_entries(
        document["packages"],
        field="distribution metadata.packages",
    )

    runtime = _parse_runtime_metadata(
        document["runtime"],
    )

    return DistributionMetadata(
        schema_version=schema_version,
        profile=profile,
        application_version=application_version,
        packages=packages,
        runtime=runtime,
    )


def _parse_runtime_metadata(
    value: object,
) -> DistributionRuntimeMetadata:
    document = _require_object(
        value,
        field="distribution metadata.runtime",
    )

    _require_exact_keys(
        document,
        field="distribution metadata.runtime",
        expected={
            "kind",
            "components",
        },
    )

    kind_value = _require_non_empty_string(
        document["kind"],
        field="distribution metadata.runtime.kind",
    )

    try:
        kind = DistributionRuntimeKind(
            kind_value,
        )
    except ValueError as exc:
        raise DistributionMetadataError(
            f"Unsupported distribution runtime kind: {kind_value!r}"
        ) from exc

    components = _parse_version_entries(
        document["components"],
        field="distribution metadata.runtime.components",
    )

    return DistributionRuntimeMetadata(
        kind=kind,
        components=components,
    )


def _parse_version_entries(
    value: object,
    *,
    field: str,
) -> VersionEntries:
    document = _require_object(
        value,
        field=field,
    )

    entries: list[tuple[str, str]] = []

    for name, version in document.items():
        component_name = _require_non_empty_string(
            name,
            field=f"{field} key",
        )

        component_version = _require_non_empty_string(
            version,
            field=f"{field}.{component_name}",
        )

        entries.append(
            (
                component_name,
                component_version,
            )
        )

    return tuple(
        sorted(entries),
    )


def _require_object(
    value: object,
    *,
    field: str,
) -> dict[str, object]:
    if not isinstance(value, dict):
        raise DistributionMetadataError(f"{field} must be a JSON object")

    document: dict[str, object] = {}

    for key, item in value.items():
        if not isinstance(key, str):
            raise DistributionMetadataError(f"{field} keys must be strings")

        document[key] = item

    return document


def _require_non_empty_string(
    value: object,
    *,
    field: str,
) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DistributionMetadataError(f"{field} must be a non-empty string")

    return value


def _require_exact_keys(
    document: dict[str, object],
    *,
    field: str,
    expected: set[str],
) -> None:
    actual = set(document)

    missing = sorted(
        expected - actual,
    )

    unexpected = sorted(
        actual - expected,
    )

    if not missing and not unexpected:
        return

    raise DistributionMetadataError(
        f"{field} has invalid fields missing={missing} unexpected={unexpected}"
    )
