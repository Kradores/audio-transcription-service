from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from zipfile import ZipFile

import pytest

from app.controller.support_bundle import (
    SupportArtifactPaths,
    SupportBundleBuilder,
    SupportBundleError,
)
from app.core.runtime_paths import (
    create_development_runtime_paths,
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
                log_file_path=(tmp_path / "logs" / "audio-transcription-service.log"),
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
