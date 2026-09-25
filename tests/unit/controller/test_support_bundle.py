from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

import pytest

from app.controller.distribution_metadata import (
    DistributionMetadata,
    DistributionMetadataError,
    DistributionProfile,
    DistributionRuntimeKind,
    DistributionRuntimeMetadata,
)
from app.controller.runtime_process import (
    RuntimeProcessDiagnosticsSnapshot,
)
from app.controller.support_bundle import (
    ConfigurationSupportArtifactPathResolver,
    DefaultSupportInfoCollector,
    SupportArtifactPaths,
    SupportBundleBuilder,
    SupportBundleError,
)
from app.core.config.enums import (
    WhisperComputeType,
    WhisperDevice,
    WhisperModel,
    WhisperRuntime,
)
from app.core.runtime_paths import (
    create_development_runtime_paths,
)
from app.models.whisper import (
    WhisperModelProvisioningState,
    WhisperModelStatus,
)
from app.observability.hardware import (
    GraphicsAdapterInfo,
    GraphicsAdaptersObservation,
)
from app.observability.transcription_runtime import (
    CTranslate2CapabilitiesObservation,
    TranscriptionRuntimeObservation,
)
from tests.unit.core.config.builders import (
    SettingsBuilder,
)


class FakePathResolver:
    def __init__(
        self,
        paths: SupportArtifactPaths,
    ) -> None:
        self._paths = paths

    def resolve(
        self,
        *,
        include_transcript_database: bool,
    ) -> SupportArtifactPaths:
        del include_transcript_database
        return self._paths


class FakeInfoCollector:
    def collect(self) -> dict[str, object]:
        return {
            "test": True,
        }


class StaticDistributionMetadataProvider:
    def __init__(
        self,
        value: DistributionMetadata,
    ) -> None:
        self._value = value

    def load(self) -> DistributionMetadata:
        return self._value


class FailingDistributionMetadataProvider:
    def load(self) -> DistributionMetadata:
        raise DistributionMetadataError("distribution metadata is invalid")


def create_builder(
    tmp_path: Path,
    *,
    database_path: Path | None = None,
) -> SupportBundleBuilder:
    runtime_paths = create_development_runtime_paths(tmp_path)

    return SupportBundleBuilder(
        runtime_paths=runtime_paths,
        path_resolver=FakePathResolver(
            SupportArtifactPaths(
                log_file_paths=(
                    (tmp_path / "logs" / "audio-transcription-service.log"),
                    (tmp_path / "logs" / "audio-transcription-service.controller.log"),
                ),
                diagnostics_directory=(tmp_path / "diagnostics"),
                transcript_database_path=database_path,
                configuration_error=None,
            )
        ),
        info_collector=FakeInfoCollector(),
        clock=lambda: datetime(
            2026,
            9,
            14,
            12,
            0,
            0,
            tzinfo=UTC,
        ),
    )


def create_runtime_diagnostics() -> RuntimeProcessDiagnosticsSnapshot:
    return RuntimeProcessDiagnosticsSnapshot(
        graphics_adapters=(
            GraphicsAdaptersObservation.success(
                (
                    GraphicsAdapterInfo(
                        name="AMD Radeon RX 6800M",
                        driver_version=("32.0.21045.5002"),
                        pnp_device_id=("PCI\\VEN_1002&DEV_73DF"),
                    ),
                )
            )
        ),
        transcription_runtime=(
            TranscriptionRuntimeObservation(
                runtime=WhisperRuntime.THEROCK,
                device=WhisperDevice.CUDA,
                configured_compute_type=(WhisperComputeType.FLOAT16),
                initialized=True,
                ctranslate2=(
                    CTranslate2CapabilitiesObservation.success(
                        cuda_device_count=1,
                        supported_compute_types=(
                            "bfloat16",
                            "float16",
                            "float32",
                            "int8",
                            "int8_bfloat16",
                            "int8_float16",
                            "int8_float32",
                        ),
                    )
                ),
            )
        ),
    )


def test_build_excludes_transcript_database_by_default(
    tmp_path: Path,
) -> None:
    # Arrange
    config_path = tmp_path / "config" / "config.yaml"
    config_path.parent.mkdir()
    config_path.write_text(
        "application:\n  name: test\n",
        encoding="utf-8",
    )

    logs_directory = tmp_path / "logs"
    logs_directory.mkdir()

    log_path = logs_directory / "audio-transcription-service.log"
    log_path.write_text(
        "application log",
        encoding="utf-8",
    )

    controller_log = logs_directory / "audio-transcription-service.controller.log"

    controller_log.write_text(
        "controller log",
        encoding="utf-8",
    )

    rotated_controller_log = logs_directory / "audio-transcription-service.controller.log.1"

    rotated_controller_log.write_text(
        "old controller log",
        encoding="utf-8",
    )

    rotated_log = logs_directory / "audio-transcription-service.log.1"
    rotated_log.write_text(
        "old log",
        encoding="utf-8",
    )

    diagnostics_directory = tmp_path / "diagnostics" / "slow-inference" / "capture-1"
    diagnostics_directory.mkdir(parents=True)

    (diagnostics_directory / "metadata.json").write_text(
        '{"duration": 1.0}',
        encoding="utf-8",
    )

    (diagnostics_directory / "audio.wav").write_bytes(b"private audio")

    (diagnostics_directory / "audio.npy").write_bytes(b"private audio")

    builder = create_builder(tmp_path)

    # Act
    result = builder.build(include_transcript_database=False)

    # Assert
    with ZipFile(result.path) as archive:
        names = set(archive.namelist())

    assert "config/config.yaml" in names
    assert "logs/audio-transcription-service.log" in names
    assert "logs/audio-transcription-service.log.1" in names
    assert "diagnostics/slow-inference/capture-1/metadata.json" in names
    assert "system-info.json" in names
    assert "manifest.json" in names
    assert "logs/audio-transcription-service.controller.log" in names
    assert "logs/audio-transcription-service.controller.log.1" in names

    assert "data/transcripts.db" not in names

    assert not any(name.endswith(".wav") for name in names)
    assert not any(name.endswith(".npy") for name in names)


def test_build_includes_consistent_database_snapshot_when_requested(
    tmp_path: Path,
) -> None:
    # Arrange
    database_path = tmp_path / "data" / "transcripts.db"
    database_path.parent.mkdir()

    source = sqlite3.connect(database_path)

    source.execute(
        """
        CREATE TABLE transcripts (
            id INTEGER PRIMARY KEY,
            text TEXT NOT NULL
        )
        """
    )
    source.execute(
        """
        INSERT INTO transcripts (text)
        VALUES ('hello')
        """
    )
    source.commit()

    builder = create_builder(
        tmp_path,
        database_path=database_path,
    )

    # Act
    result = builder.build(include_transcript_database=True)

    # Assert
    extracted_database = tmp_path / "extracted-transcripts.db"

    with ZipFile(result.path) as archive:
        extracted_database.write_bytes(archive.read("data/transcripts.db"))

    snapshot = sqlite3.connect(extracted_database)

    try:
        row = snapshot.execute(
            """
            SELECT text
            FROM transcripts
            """
        ).fetchone()
    finally:
        snapshot.close()
        source.close()

    assert row == ("hello",)


def test_build_does_not_include_raw_diagnostic_audio(
    tmp_path: Path,
) -> None:
    # Arrange
    capture_directory = tmp_path / "diagnostics" / "capture"
    capture_directory.mkdir(parents=True)

    (capture_directory / "metadata.json").write_text(
        "{}",
        encoding="utf-8",
    )
    (capture_directory / "audio.wav").write_bytes(b"audio")
    (capture_directory / "audio.npy").write_bytes(b"audio")

    builder = create_builder(tmp_path)

    # Act
    result = builder.build(include_transcript_database=False)

    # Assert
    with ZipFile(result.path) as archive:
        names = archive.namelist()

    assert any(name.endswith("metadata.json") for name in names)
    assert not any(name.endswith(".wav") for name in names)
    assert not any(name.endswith(".npy") for name in names)


def test_build_fails_when_requested_database_is_missing(
    tmp_path: Path,
) -> None:
    # Arrange
    missing_database = tmp_path / "data" / "missing.db"

    builder = create_builder(
        tmp_path,
        database_path=missing_database,
    )

    # Act / Assert
    with pytest.raises(
        SupportBundleError,
        match="does not exist",
    ):
        builder.build(include_transcript_database=True)

    support_directory = tmp_path / "support"

    assert not list(support_directory.glob("*.zip"))


def test_manifest_records_privacy_choices(
    tmp_path: Path,
) -> None:
    # Arrange
    builder = create_builder(tmp_path)

    # Act
    result = builder.build(include_transcript_database=False)

    # Assert
    with ZipFile(result.path) as archive:
        manifest = json.loads(archive.read("manifest.json"))

    assert manifest["privacy"]["transcript_database_included"] is False
    assert manifest["privacy"]["diagnostic_audio_included"] is False


def test_support_info_includes_distribution_metadata(
    tmp_path: Path,
) -> None:
    runtime_paths = create_development_runtime_paths(
        tmp_path,
    )

    distribution_metadata = DistributionMetadata(
        schema_version=1,
        profile=DistributionProfile.NVIDIA,
        application_version="0.1.0",
        packages=(
            ("ctranslate2", "4.8.1"),
            ("faster-whisper", "1.2.1"),
        ),
        runtime=DistributionRuntimeMetadata(
            kind=DistributionRuntimeKind.NVIDIA,
            components=(
                ("cublas", "12.4.5.8"),
                ("cudnn", "9.1.0.70"),
                ("nvrtc", "12.4.127"),
            ),
        ),
    )

    collector = DefaultSupportInfoCollector(
        runtime_paths,
        distribution_metadata_provider=(
            StaticDistributionMetadataProvider(
                distribution_metadata,
            )
        ),
    )

    result = collector.collect()

    assert result["distribution"] == {
        "available": True,
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


def test_support_info_reports_distribution_metadata_failure(
    tmp_path: Path,
) -> None:
    runtime_paths = create_development_runtime_paths(
        tmp_path,
    )

    collector = DefaultSupportInfoCollector(
        runtime_paths,
        distribution_metadata_provider=(FailingDistributionMetadataProvider()),
    )

    result = collector.collect()

    assert result["distribution"] == {
        "available": False,
        "error_type": "DistributionMetadataError",
        "error": "distribution metadata is invalid",
    }


def test_support_info_reports_unconfigured_distribution_metadata(
    tmp_path: Path,
) -> None:
    runtime_paths = create_development_runtime_paths(
        tmp_path,
    )

    collector = DefaultSupportInfoCollector(
        runtime_paths,
    )

    result = collector.collect()

    assert result["distribution"] == {
        "available": False,
        "error_type": "DistributionMetadataUnavailable",
        "error": "No distribution metadata provider was configured.",
    }


def test_support_info_includes_runtime_diagnostics(
    tmp_path: Path,
) -> None:
    runtime_paths = create_development_runtime_paths(
        tmp_path,
    )

    diagnostics = create_runtime_diagnostics()

    collector = DefaultSupportInfoCollector(
        runtime_paths,
        runtime_diagnostics_provider=(lambda: diagnostics),
    )

    result = collector.collect()

    assert result["hardware"] == {
        "graphics_adapters": {
            "available": True,
            "adapters": [
                {
                    "name": "AMD Radeon RX 6800M",
                    "driver_version": ("32.0.21045.5002"),
                    "pnp_device_id": ("PCI\\VEN_1002&DEV_73DF"),
                }
            ],
        }
    }

    assert result["transcription_runtime"] == {
        "available": True,
        "runtime": "therock",
        "device": "cuda",
        "configured_compute_type": "float16",
        "initialized": True,
        "ctranslate2": {
            "available": True,
            "cuda_device_count": 1,
            "supported_compute_types": [
                "bfloat16",
                "float16",
                "float32",
                "int8",
                "int8_bfloat16",
                "int8_float16",
                "int8_float32",
            ],
        },
    }


def test_support_info_reports_runtime_diagnostics_not_observed(
    tmp_path: Path,
) -> None:
    runtime_paths = create_development_runtime_paths(
        tmp_path,
    )

    diagnostics = RuntimeProcessDiagnosticsSnapshot(
        graphics_adapters=None,
        transcription_runtime=None,
    )

    collector = DefaultSupportInfoCollector(
        runtime_paths,
        runtime_diagnostics_provider=(lambda: diagnostics),
    )

    result = collector.collect()

    assert result["hardware"] == {
        "graphics_adapters": {
            "available": False,
            "adapters": [],
            "error_type": "NotObserved",
            "error": ("No graphics adapter observation is available for this controller session."),
        }
    }

    assert result["transcription_runtime"] == {
        "available": False,
        "error_type": "NotObserved",
        "error": ("No transcription runtime observation is available for this controller session."),
    }


def test_support_info_preserves_graphics_observation_failure(
    tmp_path: Path,
) -> None:
    runtime_paths = create_development_runtime_paths(
        tmp_path,
    )

    diagnostics = RuntimeProcessDiagnosticsSnapshot(
        graphics_adapters=(
            GraphicsAdaptersObservation.failure(
                error_type="PowerShellCommandError",
                error="Get-CimInstance failed",
            )
        ),
        transcription_runtime=None,
    )

    collector = DefaultSupportInfoCollector(
        runtime_paths,
        runtime_diagnostics_provider=(lambda: diagnostics),
    )

    result = collector.collect()

    assert result["hardware"] == {
        "graphics_adapters": {
            "available": False,
            "adapters": [],
            "error_type": "PowerShellCommandError",
            "error": "Get-CimInstance failed",
        }
    }


def test_support_info_includes_whisper_model_status(
    tmp_path: Path,
) -> None:
    runtime_paths = create_development_runtime_paths(tmp_path)

    status = WhisperModelStatus(
        model=WhisperModel.SMALL,
        path=runtime_paths.models_directory / "small",
        state=WhisperModelProvisioningState.READY,
    )

    collector = DefaultSupportInfoCollector(
        runtime_paths,
        whisper_model_diagnostics_provider=lambda: status,
    )

    result = collector.collect()

    assert result["whisper_model"] == {
        "observed": True,
        "model": "small",
        "path": str(runtime_paths.models_directory / "small"),
        "provisioning_state": "ready",
        "failure_message": None,
    }


def test_support_info_preserves_whisper_model_failure(
    tmp_path: Path,
) -> None:
    runtime_paths = create_development_runtime_paths(tmp_path)

    status = WhisperModelStatus(
        model=WhisperModel.SMALL,
        path=runtime_paths.models_directory / "small",
        state=WhisperModelProvisioningState.FAILED,
        failure_message=("ConnectionError: download failed"),
    )

    collector = DefaultSupportInfoCollector(
        runtime_paths,
        whisper_model_diagnostics_provider=lambda: status,
    )

    result = collector.collect()

    assert result["whisper_model"] == {
        "observed": True,
        "model": "small",
        "path": str(runtime_paths.models_directory / "small"),
        "provisioning_state": "failed",
        "failure_message": ("ConnectionError: download failed"),
    }


def test_support_info_reports_whisper_model_not_observed(
    tmp_path: Path,
) -> None:
    collector = DefaultSupportInfoCollector(create_development_runtime_paths(tmp_path))

    result = collector.collect()

    assert result["whisper_model"] == {
        "observed": False,
        "error_type": "NotObserved",
        "error": ("No Whisper model status observation is available for this controller session."),
    }


def test_build_deduplicates_configured_log_paths(
    tmp_path: Path,
) -> None:
    runtime_paths = create_development_runtime_paths(tmp_path)

    log_path = tmp_path / "logs" / "application.log"

    log_path.parent.mkdir(
        parents=True,
    )

    log_path.write_text(
        "log",
        encoding="utf-8",
    )

    builder = SupportBundleBuilder(
        runtime_paths=runtime_paths,
        path_resolver=FakePathResolver(
            SupportArtifactPaths(
                log_file_paths=(
                    log_path,
                    log_path,
                ),
                diagnostics_directory=(tmp_path / "diagnostics"),
                transcript_database_path=None,
                configuration_error=None,
            )
        ),
        info_collector=FakeInfoCollector(),
        clock=lambda: datetime(
            2026,
            9,
            14,
            12,
            0,
            0,
            tzinfo=UTC,
        ),
    )

    result = builder.build(include_transcript_database=False)

    with ZipFile(result.path) as archive:
        names = archive.namelist()

    assert names.count("logs/application.log") == 1


# File: tests/unit/controller/test_support_bundle.py


def test_support_artifact_paths_include_runtime_and_controller_logs(
    tmp_path: Path,
) -> None:
    runtime_paths = create_development_runtime_paths(tmp_path)

    settings = SettingsBuilder().build()

    runtime_log_path = tmp_path / "logs" / "audio-transcription-service.log"

    resolved_settings = settings.model_copy(
        update={
            "logging": (
                settings.logging.model_copy(
                    update={
                        "file": (
                            settings.logging.file.model_copy(
                                update={
                                    "path": runtime_log_path,
                                }
                            )
                        )
                    }
                )
            )
        }
    )

    with patch("app.controller.support_bundle.ConfigurationLoader") as loader_type:
        loader_type.return_value.load.return_value = resolved_settings

        resolver = ConfigurationSupportArtifactPathResolver(runtime_paths)

        result = resolver.resolve(include_transcript_database=False)

    assert result.log_file_paths == (
        runtime_log_path,
        (tmp_path / "logs" / "audio-transcription-service.controller.log"),
    )
