from __future__ import annotations

import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from huggingface_hub import snapshot_download

from app.core.config.enums import WhisperModel
from app.models.whisper import (
    WHISPER_MODEL_ARTIFACT_PATTERNS,
    WHISPER_MODEL_READY_MARKER_NAME,
    ResolvedWhisperModel,
    WhisperModelResolver,
    WhisperModelValidationError,
    validate_whisper_model_contents,
)

WHISPER_MODEL_REPOSITORIES: dict[WhisperModel, str] = {
    WhisperModel.TINY: "Systran/faster-whisper-tiny",
    WhisperModel.BASE: "Systran/faster-whisper-base",
    WhisperModel.SMALL: "Systran/faster-whisper-small",
    WhisperModel.MEDIUM: "Systran/faster-whisper-medium",
    WhisperModel.LARGE: "Systran/faster-whisper-large-v3",
    WhisperModel.TURBO: "mobiuslabsgmbh/faster-whisper-large-v3-turbo",
}

WHISPER_MODEL_DOWNLOAD_PATTERNS = (
    "config.json",
    "preprocessor_config.json",
    "model.bin",
    "tokenizer.json",
    "vocabulary.*",
)


type SnapshotDownloader = Callable[[str, Path], None]


class WhisperModelProvisioner(Protocol):
    def provision(
        self,
        model: WhisperModel,
    ) -> ResolvedWhisperModel:
        """Provision one Whisper model and return the published model."""


def download_whisper_model_snapshot(
    repository_id: str,
    destination: Path,
) -> None:
    snapshot_download(
        repo_id=repository_id,
        local_dir=destination,
        allow_patterns=list(WHISPER_MODEL_ARTIFACT_PATTERNS),
    )


class WhisperModelProvisioningError(RuntimeError):
    """Raised when a Whisper model cannot be safely provisioned."""


class HuggingFaceWhisperModelProvisioner:
    """Provision application-owned Whisper models from Hugging Face."""

    def __init__(
        self,
        *,
        resolver: WhisperModelResolver,
        downloader: SnapshotDownloader = download_whisper_model_snapshot,
    ) -> None:
        self._resolver = resolver
        self._downloader = downloader

    def provision(
        self,
        model: WhisperModel,
    ) -> ResolvedWhisperModel:
        resolved = self._resolver.resolve(model)

        if resolved.ready:
            return resolved

        repository_id = WHISPER_MODEL_REPOSITORIES[model]

        resolved.path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        temporary_path = resolved.path.with_name(f".{resolved.path.name}.download")

        temporary_path.mkdir(
            parents=True,
            exist_ok=True,
        )

        self._downloader(
            repository_id,
            temporary_path,
        )

        self._validate_download(temporary_path)

        (temporary_path / WHISPER_MODEL_READY_MARKER_NAME).touch()

        if resolved.path.exists():
            shutil.rmtree(resolved.path)

        temporary_path.replace(resolved.path)

        provisioned = self._resolver.resolve(model)

        if not provisioned.ready:
            raise WhisperModelProvisioningError(
                f"Whisper model '{model.value}' was downloaded but was not published as ready"
            )

        return provisioned

    @staticmethod
    def _validate_download(
        model_directory: Path,
    ) -> None:
        try:
            validate_whisper_model_contents(model_directory)
        except WhisperModelValidationError as exc:
            raise WhisperModelProvisioningError(str(exc)) from exc
