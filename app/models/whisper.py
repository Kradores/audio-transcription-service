from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from app.core.config.enums import WhisperModel

WHISPER_MODEL_READY_MARKER_NAME = ".ready"


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
