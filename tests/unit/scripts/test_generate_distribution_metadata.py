from __future__ import annotations

import json
from importlib import metadata
from pathlib import Path

import pytest

from app.controller.distribution_metadata import (
    DistributionProfile,
    DistributionRuntimeKind,
)
from scripts.generate_distribution_metadata import (
    DistributionMetadataGenerationError,
    create_distribution_metadata,
)


def write_project(
    root: Path,
) -> None:
    (root / "pyproject.toml").write_text(
        """
[project]
name = "audio-transcription-service"
version = "0.1.0"
""".strip(),
        encoding="utf-8",
    )


def version_resolver(
    package_name: str,
) -> str:
    versions = {
        "faster-whisper": "1.2.1",
        "ctranslate2": "4.8.1",
        "torch": "2.9.0",
        "pyaudiowpatch": "0.2.12.8",
        "pycaw": "20251023",
        "silero-vad": "6.2.1",
        "soxr": "1.1.0",
    }

    try:
        return versions[package_name]
    except KeyError as exc:
        raise metadata.PackageNotFoundError(package_name) from exc


def test_cpu_metadata_uses_default_runtime(
    tmp_path: Path,
) -> None:
    write_project(tmp_path)

    result = create_distribution_metadata(
        profile=DistributionProfile.CPU,
        project_root=tmp_path,
        version_resolver=version_resolver,
    )

    assert result.profile is DistributionProfile.CPU
    assert result.application_version == "0.1.0"

    assert result.runtime is not None
    assert result.runtime.kind is DistributionRuntimeKind.DEFAULT
    assert result.runtime.components == ()

    assert dict(result.packages)["audio-transcription-service"] == "0.1.0"

    assert dict(result.packages)["faster-whisper"] == "1.2.1"

    assert dict(result.packages)["ctranslate2"] == "4.8.1"


def test_nvidia_metadata_uses_prepared_runtime_versions(
    tmp_path: Path,
) -> None:
    write_project(tmp_path)

    toolchain_directory = tmp_path / "scripts" / "nvidia"
    toolchain_directory.mkdir(
        parents=True,
    )

    (toolchain_directory / "toolchain.json").write_text(
        json.dumps(
            {
                "runtime": {
                    "faster_whisper": "1.2.1",
                    "ctranslate2": "4.8.1",
                },
                "nvidia": {
                    "packages": {
                        "nvidia-cublas-cu12": "12.4.5.8",
                        "nvidia-cudnn-cu12": "9.1.0.70",
                        "nvidia-cuda-nvrtc-cu12": "12.4.127",
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    runtime_manifest = tmp_path / "runtime-manifest.json"

    runtime_manifest.write_text(
        json.dumps(
            {
                "packages": {
                    "nvidia-cublas-cu12": "12.4.5.8",
                    "nvidia-cudnn-cu12": "9.1.0.70",
                    "nvidia-cuda-nvrtc-cu12": "12.4.127",
                }
            }
        ),
        encoding="utf-8",
    )

    result = create_distribution_metadata(
        profile=DistributionProfile.NVIDIA,
        project_root=tmp_path,
        version_resolver=version_resolver,
        nvidia_runtime_manifest_path=runtime_manifest,
    )

    assert result.runtime is not None
    assert result.runtime.kind is DistributionRuntimeKind.NVIDIA

    assert dict(result.runtime.components) == {
        "cublas": "12.4.5.8",
        "cudnn": "9.1.0.70",
        "nvrtc": "12.4.127",
    }


def test_nvidia_metadata_rejects_python_runtime_mismatch(
    tmp_path: Path,
) -> None:
    write_project(tmp_path)

    toolchain_directory = tmp_path / "scripts" / "nvidia"
    toolchain_directory.mkdir(
        parents=True,
    )

    (toolchain_directory / "toolchain.json").write_text(
        json.dumps(
            {
                "runtime": {
                    "faster_whisper": "1.2.1",
                    "ctranslate2": "4.8.1",
                },
                "nvidia": {
                    "packages": {
                        "nvidia-cublas-cu12": "12.4.5.8",
                        "nvidia-cudnn-cu12": "9.1.0.70",
                        "nvidia-cuda-nvrtc-cu12": "12.4.127",
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    runtime_manifest = tmp_path / "runtime-manifest.json"

    runtime_manifest.write_text(
        json.dumps(
            {
                "packages": {
                    "nvidia-cublas-cu12": "12.4.5.8",
                    "nvidia-cudnn-cu12": "9.1.0.70",
                    "nvidia-cuda-nvrtc-cu12": "12.4.127",
                }
            }
        ),
        encoding="utf-8",
    )

    def mismatched_version_resolver(
        package_name: str,
    ) -> str:
        if package_name == "ctranslate2":
            return "4.9.0"

        return version_resolver(package_name)

    with pytest.raises(
        DistributionMetadataGenerationError,
        match="does not match NVIDIA toolchain",
    ):
        create_distribution_metadata(
            profile=DistributionProfile.NVIDIA,
            project_root=tmp_path,
            version_resolver=mismatched_version_resolver,
            nvidia_runtime_manifest_path=(runtime_manifest),
        )


def test_generation_fails_when_required_package_is_missing(
    tmp_path: Path,
) -> None:
    write_project(tmp_path)

    def missing_version_resolver(
        package_name: str,
    ) -> str:
        if package_name == "ctranslate2":
            raise metadata.PackageNotFoundError(package_name)

        return version_resolver(package_name)

    with pytest.raises(
        DistributionMetadataGenerationError,
        match="ctranslate2",
    ):
        create_distribution_metadata(
            profile=DistributionProfile.CPU,
            project_root=tmp_path,
            version_resolver=missing_version_resolver,
        )


def test_amd_metadata_uses_pinned_therock_runtime(
    tmp_path: Path,
) -> None:
    write_project(tmp_path)

    toolchain_directory = tmp_path / "scripts" / "amd"

    toolchain_directory.mkdir(
        parents=True,
    )

    (toolchain_directory / "toolchain.json").write_text(
        json.dumps(
            {
                "required": {
                    "ctranslate2": {
                        "version": "4.8.1",
                        "hip_architecture": "gfx1031",
                    },
                    "therock": {
                        "packages": {
                            "rocm": "10.1.0a20260829",
                            "rocm-sdk-core": "10.1.0a20260829",
                            "rocm-sdk-devel": "10.1.0a20260829",
                            "rocm-sdk-device-gfx1031": ("10.1.0a20260829"),
                            "rocm-sdk-libraries": ("10.1.0a20260829"),
                        }
                    },
                    "intel_oneapi": {
                        "version": "2026.1",
                    },
                }
            }
        ),
        encoding="utf-8",
    )

    result = create_distribution_metadata(
        profile=DistributionProfile.AMD,
        project_root=tmp_path,
        version_resolver=version_resolver,
    )

    assert result.profile is DistributionProfile.AMD

    assert result.runtime is not None
    assert result.runtime.kind is DistributionRuntimeKind.THEROCK

    assert dict(result.runtime.components) == {
        "intel-openmp": "2026.1",
        "rocm": "10.1.0a20260829",
        "rocm-sdk-core": "10.1.0a20260829",
        "rocm-sdk-device-gfx1031": ("10.1.0a20260829"),
        "rocm-sdk-libraries": ("10.1.0a20260829"),
    }


def test_amd_metadata_rejects_ctranslate2_version_mismatch(
    tmp_path: Path,
) -> None:
    write_project(tmp_path)

    toolchain_directory = tmp_path / "scripts" / "amd"

    toolchain_directory.mkdir(
        parents=True,
    )

    (toolchain_directory / "toolchain.json").write_text(
        json.dumps(
            {
                "required": {
                    "ctranslate2": {
                        "version": "4.9.0",
                    },
                    "therock": {"packages": {}},
                    "intel_oneapi": {
                        "version": "2026.1",
                    },
                }
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        DistributionMetadataGenerationError,
        match="ctranslate2",
    ):
        create_distribution_metadata(
            profile=DistributionProfile.AMD,
            project_root=tmp_path,
            version_resolver=version_resolver,
        )
