from __future__ import annotations

import json
import logging
import os
import platform
import sqlite3
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Protocol
from zipfile import ZIP_DEFLATED, ZipFile

from app.controller.distribution_metadata import (
    DistributionMetadataError,
    DistributionMetadataProvider,
)
from app.core.config.exceptions import ConfigurationError
from app.core.config.loader import ConfigurationLoader
from app.core.runtime_paths import RuntimePaths

logger = logging.getLogger(__name__)

_SUPPORT_BUNDLE_SCHEMA_VERSION = 1

_PACKAGE_NAMES = (
    "audio-transcription-service",
    "faster-whisper",
    "ctranslate2",
    "torch",
    "pyaudiowpatch",
    "pycaw",
    "silero-vad",
    "soxr",
)


class SupportBundleError(Exception):
    """Raised when a requested support bundle cannot be created."""


@dataclass(frozen=True, slots=True)
class SupportBundleResult:
    path: Path
    included_files: tuple[str, ...]
    warnings: tuple[str, ...]
    transcript_database_included: bool


class SupportBundleCreator(Protocol):
    def build(
        self,
        *,
        include_transcript_database: bool,
    ) -> SupportBundleResult:
        """Create one support bundle."""


@dataclass(frozen=True, slots=True)
class SupportArtifactPaths:
    log_file_path: Path | None
    diagnostics_directory: Path
    transcript_database_path: Path | None
    configuration_error: str | None


class SupportArtifactPathResolver(Protocol):
    def resolve(
        self,
        *,
        include_transcript_database: bool,
    ) -> SupportArtifactPaths:
        """Resolve configured support-artifact paths."""


class SupportInfoCollector(Protocol):
    def collect(self) -> dict[str, object]:
        """Collect non-content diagnostic information."""


class ConfigurationSupportArtifactPathResolver:
    """Resolve support artifacts through the normal application config."""

    def __init__(
        self,
        runtime_paths: RuntimePaths,
    ) -> None:
        self._runtime_paths = runtime_paths

    def resolve(
        self,
        *,
        include_transcript_database: bool,
    ) -> SupportArtifactPaths:
        try:
            settings = ConfigurationLoader(self._runtime_paths).load()
        except ConfigurationError as exc:
            if include_transcript_database:
                raise SupportBundleError(
                    "Cannot include the transcript database because "
                    "the application configuration could not be loaded."
                ) from exc

            return SupportArtifactPaths(
                log_file_path=None,
                diagnostics_directory=(self._runtime_paths.diagnostics_directory),
                transcript_database_path=None,
                configuration_error=(f"{type(exc).__name__}: {exc}"),
            )

        return SupportArtifactPaths(
            log_file_path=settings.logging.file.path,
            diagnostics_directory=(settings.whisper.slow_inference_capture.directory),
            transcript_database_path=(
                settings.database.path if include_transcript_database else None
            ),
            configuration_error=None,
        )


# app/controller/support_bundle.py


class DefaultSupportInfoCollector:
    """Collect lightweight environment and runtime information."""

    def __init__(
        self,
        runtime_paths: RuntimePaths,
        *,
        distribution_metadata_provider: DistributionMetadataProvider | None = None,
    ) -> None:
        self._runtime_paths = runtime_paths
        self._distribution_metadata_provider = distribution_metadata_provider

    def collect(self) -> dict[str, object]:
        return {
            "python": {
                "version": sys.version,
                "executable": sys.executable,
            },
            "operating_system": {
                "platform": platform.platform(),
                "system": platform.system(),
                "release": platform.release(),
                "version": platform.version(),
                "machine": platform.machine(),
                "processor": platform.processor(),
                "logical_cpu_count": os.cpu_count(),
            },
            "runtime": {
                "root_directory": str(self._runtime_paths.root_directory),
                "config_path": str(self._runtime_paths.config_path),
            },
            "distribution": self._collect_distribution_metadata(),
            "packages": self._collect_package_versions(),
            "configuration": self._collect_configuration(),
        }

    def _collect_package_versions(
        self,
    ) -> dict[str, str | None]:
        versions: dict[str, str | None] = {}

        for package_name in _PACKAGE_NAMES:
            try:
                versions[package_name] = metadata.version(package_name)
            except metadata.PackageNotFoundError:
                versions[package_name] = None

        return versions

    def _collect_configuration(
        self,
    ) -> dict[str, object]:
        try:
            settings = ConfigurationLoader(self._runtime_paths).load()
        except ConfigurationError as exc:
            return {
                "available": False,
                "error_type": type(exc).__name__,
                "error": str(exc),
            }

        return {
            "available": True,
            "application": {
                "name": settings.application.name,
                "environment": (settings.application.environment.value),
            },
            "whisper": {
                "model": settings.whisper.model.value,
                "runtime": settings.whisper.runtime.value,
                "device": settings.whisper.device.value,
                "compute_type": (settings.whisper.compute_type.value),
            },
            "audio": {
                "sample_rate": (settings.audio.processing.sample_rate),
                "channels": settings.audio.processing.channels,
            },
            "transcription": {
                "worker_count": (settings.transcription.worker_count),
                "queue_capacity": (settings.transcription.queue_capacity),
            },
            "logging": {
                "enabled": settings.logging.file.enabled,
                "path": str(settings.logging.file.path),
            },
            "database": {
                "path": str(settings.database.path),
            },
        }

    def _collect_distribution_metadata(
        self,
    ) -> dict[str, object]:
        provider = self._distribution_metadata_provider

        if provider is None:
            return {
                "available": False,
                "error_type": "DistributionMetadataUnavailable",
                "error": "No distribution metadata provider was configured.",
            }

        try:
            distribution_metadata = provider.load()
        except DistributionMetadataError as exc:
            return {
                "available": False,
                "error_type": type(exc).__name__,
                "error": str(exc),
            }

        return {
            "available": True,
            **distribution_metadata.to_dict(),
        }


def _utc_now() -> datetime:
    return datetime.now(UTC)


class SupportBundleBuilder:
    """Build one privacy-conscious diagnostic ZIP."""

    def __init__(
        self,
        *,
        runtime_paths: RuntimePaths,
        path_resolver: SupportArtifactPathResolver,
        info_collector: SupportInfoCollector,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._runtime_paths = runtime_paths
        self._path_resolver = path_resolver
        self._info_collector = info_collector
        self._clock = clock

    def build(
        self,
        *,
        include_transcript_database: bool,
    ) -> SupportBundleResult:
        created_at = self._clock().astimezone(UTC)

        bundle_name = f"support-{created_at.strftime('%Y%m%dT%H%M%S.%fZ')}.zip"

        support_directory = self._runtime_paths.support_directory
        support_directory.mkdir(
            parents=True,
            exist_ok=True,
        )

        bundle_path = support_directory / bundle_name
        temporary_path = support_directory / f".{bundle_name}.tmp"

        included_files: list[str] = []
        warnings: list[str] = []

        artifact_paths = self._path_resolver.resolve(
            include_transcript_database=(include_transcript_database)
        )

        if artifact_paths.configuration_error is not None:
            warnings.append(
                "Application configuration could not be loaded: "
                f"{artifact_paths.configuration_error}"
            )

        try:
            with ZipFile(
                temporary_path,
                mode="w",
                compression=ZIP_DEFLATED,
            ) as archive:
                self._add_configuration(
                    archive,
                    included_files,
                    warnings,
                )

                self._add_application_logs(
                    archive,
                    artifact_paths=artifact_paths,
                    included_files=included_files,
                    warnings=warnings,
                )

                self._add_diagnostic_metadata(
                    archive,
                    diagnostics_directory=(artifact_paths.diagnostics_directory),
                    included_files=included_files,
                    warnings=warnings,
                )

                system_info = self._info_collector.collect()

                self._write_json(
                    archive,
                    archive_path="system-info.json",
                    value=system_info,
                )
                included_files.append("system-info.json")

                if include_transcript_database:
                    database_path = artifact_paths.transcript_database_path

                    if database_path is None:
                        raise SupportBundleError("Transcript database path could not be resolved.")

                    self._add_database_snapshot(
                        archive,
                        database_path=database_path,
                    )
                    included_files.append("data/transcripts.db")

                manifest_files = sorted(
                    [
                        *included_files,
                        "manifest.json",
                    ]
                )

                manifest = {
                    "schema_version": (_SUPPORT_BUNDLE_SCHEMA_VERSION),
                    "created_at_utc": (created_at.isoformat()),
                    "privacy": {
                        "transcript_database_included": (include_transcript_database),
                        "diagnostic_audio_included": False,
                    },
                    "included_files": manifest_files,
                    "warnings": warnings,
                }

                self._write_json(
                    archive,
                    archive_path="manifest.json",
                    value=manifest,
                )

                included_files.append("manifest.json")

            temporary_path.replace(bundle_path)

        except Exception:
            temporary_path.unlink(
                missing_ok=True,
            )
            raise

        logger.info(
            "support bundle created path=%s transcript_database_included=%s files=%d warnings=%d",
            bundle_path,
            include_transcript_database,
            len(included_files),
            len(warnings),
        )

        return SupportBundleResult(
            path=bundle_path,
            included_files=tuple(sorted(included_files)),
            warnings=tuple(warnings),
            transcript_database_included=(include_transcript_database),
        )

    def _add_configuration(
        self,
        archive: ZipFile,
        included_files: list[str],
        warnings: list[str],
    ) -> None:
        config_path = self._runtime_paths.config_path

        if not config_path.is_file():
            warnings.append(f"Configuration file not found: {config_path}")
            return

        self._add_file(
            archive,
            source_path=config_path,
            archive_path="config/config.yaml",
            included_files=included_files,
            warnings=warnings,
        )

    def _add_application_logs(
        self,
        archive: ZipFile,
        *,
        artifact_paths: SupportArtifactPaths,
        included_files: list[str],
        warnings: list[str],
    ) -> None:
        configured_log = artifact_paths.log_file_path

        if configured_log is not None:
            candidates = [
                configured_log,
                *sorted(configured_log.parent.glob(f"{configured_log.name}.*")),
            ]
        else:
            candidates = sorted(self._runtime_paths.logs_directory.glob("*.log*"))

        for log_path in candidates:
            if not log_path.is_file():
                continue

            self._add_file(
                archive,
                source_path=log_path,
                archive_path=(f"logs/{log_path.name}"),
                included_files=included_files,
                warnings=warnings,
            )

    def _add_diagnostic_metadata(
        self,
        archive: ZipFile,
        *,
        diagnostics_directory: Path,
        included_files: list[str],
        warnings: list[str],
    ) -> None:
        if not diagnostics_directory.is_dir():
            return

        for metadata_path in sorted(diagnostics_directory.rglob("metadata.json")):
            relative_path = metadata_path.relative_to(diagnostics_directory)

            archive_path = (Path("diagnostics") / relative_path).as_posix()

            self._add_file(
                archive,
                source_path=metadata_path,
                archive_path=archive_path,
                included_files=included_files,
                warnings=warnings,
            )

    def _add_database_snapshot(
        self,
        archive: ZipFile,
        *,
        database_path: Path,
    ) -> None:
        if not database_path.is_file():
            raise SupportBundleError(f"Transcript database does not exist: {database_path}")

        try:
            with TemporaryDirectory(prefix="audio-transcription-support-") as temporary_directory:
                snapshot_path = Path(temporary_directory) / "transcripts.db"

                source = sqlite3.connect(
                    database_path,
                    timeout=5.0,
                )

                try:
                    destination = sqlite3.connect(snapshot_path)

                    try:
                        source.backup(destination)
                    finally:
                        destination.close()

                finally:
                    source.close()

                archive.write(
                    snapshot_path,
                    arcname="data/transcripts.db",
                )

        except sqlite3.Error as exc:
            raise SupportBundleError(
                "Could not create a consistent transcript database snapshot."
            ) from exc

    @staticmethod
    def _add_file(
        archive: ZipFile,
        *,
        source_path: Path,
        archive_path: str,
        included_files: list[str],
        warnings: list[str],
    ) -> None:
        try:
            archive.write(
                source_path,
                arcname=archive_path,
            )
        except OSError as exc:
            warning = f"Could not include {source_path}: {type(exc).__name__}: {exc}"
            warnings.append(warning)
            logger.warning(
                "support bundle file skipped path=%s error_type=%s error=%r",
                source_path,
                type(exc).__name__,
                exc,
            )
            return

        included_files.append(archive_path)

    @staticmethod
    def _write_json(
        archive: ZipFile,
        *,
        archive_path: str,
        value: object,
    ) -> None:
        archive.writestr(
            archive_path,
            json.dumps(
                value,
                indent=2,
                ensure_ascii=False,
            ),
        )
