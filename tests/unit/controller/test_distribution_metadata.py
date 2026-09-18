from __future__ import annotations

import json
from importlib import metadata
from pathlib import Path

import pytest

from app.controller.distribution_metadata import (
    DISTRIBUTION_METADATA_SCHEMA_VERSION,
    DevelopmentDistributionMetadataProvider,
    DistributionMetadataError,
    DistributionProfile,
    DistributionRuntimeKind,
    FileDistributionMetadataProvider,
)


def write_metadata(
    path: Path,
    document: object,
) -> None:
    path.write_text(
        json.dumps(
            document,
            indent=2,
        ),
        encoding="utf-8",
    )


def valid_document() -> dict[str, object]:
    return {
        "schema_version": 1,
        "profile": "nvidia",
        "application_version": "0.1.0",
        "packages": {
            "ctranslate2": "4.8.1",
            "faster-whisper": "1.2.1",
        },
        "runtime": {
            "kind": "nvidia",
            "components": {
                "cublas": "12.4.5.8",
                "cudnn": "9.1.0.70",
                "nvrtc": "12.4.127",
            },
        },
    }


def test_file_provider_loads_valid_metadata(
    tmp_path: Path,
) -> None:
    path = tmp_path / "distribution-metadata.json"

    write_metadata(
        path,
        valid_document(),
    )

    result = FileDistributionMetadataProvider(
        path,
    ).load()

    assert result.schema_version == DISTRIBUTION_METADATA_SCHEMA_VERSION
    assert result.profile is DistributionProfile.NVIDIA
    assert result.application_version == "0.1.0"

    assert dict(result.packages) == {
        "ctranslate2": "4.8.1",
        "faster-whisper": "1.2.1",
    }

    assert result.runtime is not None
    assert result.runtime.kind is DistributionRuntimeKind.NVIDIA

    assert dict(result.runtime.components) == {
        "cublas": "12.4.5.8",
        "cudnn": "9.1.0.70",
        "nvrtc": "12.4.127",
    }


def test_file_provider_rejects_unsupported_schema_version(
    tmp_path: Path,
) -> None:
    document = valid_document()
    document["schema_version"] = 2

    path = tmp_path / "distribution-metadata.json"

    write_metadata(
        path,
        document,
    )

    with pytest.raises(
        DistributionMetadataError,
        match="Unsupported distribution metadata schema version",
    ):
        FileDistributionMetadataProvider(
            path,
        ).load()


def test_file_provider_rejects_invalid_profile(
    tmp_path: Path,
) -> None:
    document = valid_document()
    document["profile"] = "unknown"

    path = tmp_path / "distribution-metadata.json"

    write_metadata(
        path,
        document,
    )

    with pytest.raises(
        DistributionMetadataError,
        match="Unsupported distribution profile",
    ):
        FileDistributionMetadataProvider(
            path,
        ).load()


def test_file_provider_rejects_invalid_runtime_kind(
    tmp_path: Path,
) -> None:
    document = valid_document()

    runtime = document["runtime"]

    assert isinstance(
        runtime,
        dict,
    )

    runtime["kind"] = "unknown"

    path = tmp_path / "distribution-metadata.json"

    write_metadata(
        path,
        document,
    )

    with pytest.raises(
        DistributionMetadataError,
        match="Unsupported distribution runtime kind",
    ):
        FileDistributionMetadataProvider(
            path,
        ).load()


def test_file_provider_rejects_missing_required_field(
    tmp_path: Path,
) -> None:
    document = valid_document()
    del document["application_version"]

    path = tmp_path / "distribution-metadata.json"

    write_metadata(
        path,
        document,
    )

    with pytest.raises(
        DistributionMetadataError,
        match="missing=.*application_version",
    ):
        FileDistributionMetadataProvider(
            path,
        ).load()


def test_file_provider_rejects_unexpected_field(
    tmp_path: Path,
) -> None:
    document = valid_document()
    document["unexpected"] = True

    path = tmp_path / "distribution-metadata.json"

    write_metadata(
        path,
        document,
    )

    with pytest.raises(
        DistributionMetadataError,
        match="unexpected=.*unexpected",
    ):
        FileDistributionMetadataProvider(
            path,
        ).load()


def test_file_provider_rejects_empty_package_version(
    tmp_path: Path,
) -> None:
    document = valid_document()

    packages = document["packages"]

    assert isinstance(
        packages,
        dict,
    )

    packages["ctranslate2"] = ""

    path = tmp_path / "distribution-metadata.json"

    write_metadata(
        path,
        document,
    )

    with pytest.raises(
        DistributionMetadataError,
        match="must be a non-empty string",
    ):
        FileDistributionMetadataProvider(
            path,
        ).load()


def test_file_provider_rejects_malformed_json(
    tmp_path: Path,
) -> None:
    path = tmp_path / "distribution-metadata.json"

    path.write_text(
        "{invalid",
        encoding="utf-8",
    )

    with pytest.raises(
        DistributionMetadataError,
        match="Could not load distribution metadata",
    ):
        FileDistributionMetadataProvider(
            path,
        ).load()


def test_file_provider_reports_missing_file(
    tmp_path: Path,
) -> None:
    path = tmp_path / "missing.json"

    with pytest.raises(
        DistributionMetadataError,
        match="Could not load distribution metadata",
    ):
        FileDistributionMetadataProvider(
            path,
        ).load()


def test_development_provider_creates_development_metadata() -> None:
    versions = {
        "audio-transcription-service": "0.1.0",
        "faster-whisper": "1.2.1",
        "ctranslate2": "4.8.1",
    }

    def resolve_version(
        package_name: str,
    ) -> str:
        try:
            return versions[package_name]
        except KeyError as exc:
            raise metadata.PackageNotFoundError(package_name) from exc

    result = DevelopmentDistributionMetadataProvider(
        package_names=(
            "audio-transcription-service",
            "faster-whisper",
            "ctranslate2",
            "missing-package",
        ),
        version_resolver=resolve_version,
    ).load()

    assert result.profile is DistributionProfile.DEVELOPMENT
    assert result.application_version == "0.1.0"
    assert result.runtime is None

    assert dict(result.packages) == {
        "audio-transcription-service": "0.1.0",
        "ctranslate2": "4.8.1",
        "faster-whisper": "1.2.1",
    }


def test_development_provider_requires_application_metadata() -> None:
    def resolve_version(
        package_name: str,
    ) -> str:
        raise metadata.PackageNotFoundError(package_name)

    provider = DevelopmentDistributionMetadataProvider(
        version_resolver=resolve_version,
    )

    with pytest.raises(
        DistributionMetadataError,
        match="Application package metadata is unavailable",
    ):
        provider.load()


def test_metadata_serializes_to_diagnostic_structure(
    tmp_path: Path,
) -> None:
    path = tmp_path / "distribution-metadata.json"

    write_metadata(
        path,
        valid_document(),
    )

    result = FileDistributionMetadataProvider(
        path,
    ).load()

    assert result.to_dict() == {
        "schema_version": 1,
        "profile": "nvidia",
        "application_version": "0.1.0",
        "packages": {
            "ctranslate2": "4.8.1",
            "faster-whisper": "1.2.1",
        },
        "runtime": {
            "kind": "nvidia",
            "components": {
                "cublas": "12.4.5.8",
                "cudnn": "9.1.0.70",
                "nvrtc": "12.4.127",
            },
        },
    }
