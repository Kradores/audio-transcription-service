from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from app.core.config.enums import WhisperModel

WHISPER_MODEL_READY_MARKER_NAME = ".ready"


WHISPER_MODEL_ARTIFACT_PATTERNS = (
    "config.json",
    "preprocessor_config.json",
    "model.bin",
    "tokenizer.json",
    "vocabulary.*",
)

WHISPER_MODEL_REQUIRED_FILE_NAMES = (
    "config.json",
    "model.bin",
    "tokenizer.json",
)


class WhisperModelValidationError(RuntimeError):
    """Raised when a local Whisper model directory is invalid."""


def validate_whisper_model_contents(
    model_directory: Path,
) -> None:
    if not model_directory.is_dir():
        raise WhisperModelValidationError(
            f"Whisper model directory does not exist: '{model_directory}'"
        )

    missing = tuple(
        file_name
        for file_name in WHISPER_MODEL_REQUIRED_FILE_NAMES
        if not (model_directory / file_name).is_file()
    )

    if missing:
        raise WhisperModelValidationError(
            f"Whisper model directory is incomplete path='{model_directory}' missing={missing}"
        )


def validate_ready_whisper_model_directory(
    model_directory: Path,
) -> None:
    validate_whisper_model_contents(model_directory)

    marker_path = model_directory / WHISPER_MODEL_READY_MARKER_NAME

    if not marker_path.is_file():
        raise WhisperModelValidationError(
            f"Whisper model is not published as ready path='{model_directory}'"
        )


@dataclass(frozen=True, slots=True)
class ResolvedWhisperModel:
    """Resolve one logical Whisper model to application-owned storage."""

    model: WhisperModel
    path: Path
    ready: bool


class WhisperModelResolver(Protocol):
    def resolve(
        self,
        model: WhisperModel,
    ) -> ResolvedWhisperModel:
        """Resolve one configured Whisper model."""


class LocalWhisperModelResolver:
    """Resolve Whisper models from the application-owned model directory."""

    def __init__(
        self,
        models_directory: Path,
    ) -> None:
        self._models_directory = models_directory

    def resolve(
        self,
        model: WhisperModel,
    ) -> ResolvedWhisperModel:
        model_path = self._models_directory / model.value
        ready_marker = model_path / WHISPER_MODEL_READY_MARKER_NAME

        return ResolvedWhisperModel(
            model=model,
            path=model_path,
            ready=ready_marker.is_file(),
        )


class WhisperModelNotReadyError(RuntimeError):
    """Raised when the configured Whisper model is not locally ready."""


def resolve_ready_whisper_model(
    resolver: WhisperModelResolver,
    model: WhisperModel,
) -> ResolvedWhisperModel:
    resolved = resolver.resolve(model)

    if not resolved.ready:
        raise WhisperModelNotReadyError(
            f"Whisper model '{model.value}' is not installed locally at '{resolved.path}'"
        )

    return resolved


class WhisperModelProvisioningState(StrEnum):
    NOT_INSTALLED = "not_installed"
    DOWNLOADING = "downloading"
    READY = "ready"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class WhisperModelStatus:
    model: WhisperModel
    path: Path
    state: WhisperModelProvisioningState
    failure_message: str | None = None
