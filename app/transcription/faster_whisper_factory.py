from __future__ import annotations

import importlib
from collections.abc import Callable
from typing import Protocol, cast

from app.transcription.faster_whisper_runtime import (
    FasterWhisperRuntimeInitializer,
)
from app.transcription.protocols import WhisperModelProtocol


class _WhisperModelConstructor(Protocol):
    def __call__(
        self,
        model_size_or_path: str,
        *,
        device: str,
        compute_type: str,
        num_workers: int,
    ) -> WhisperModelProtocol:
        """Create a Faster-Whisper model."""


type WhisperModelLoader = Callable[[], _WhisperModelConstructor]


def _load_whisper_model() -> _WhisperModelConstructor:
    module = importlib.import_module("faster_whisper")
    return cast(_WhisperModelConstructor, module.WhisperModel)


class FasterWhisperModelFactory:
    def __init__(
        self,
        runtime_initializer: FasterWhisperRuntimeInitializer,
        model_loader: WhisperModelLoader = _load_whisper_model,
    ) -> None:
        self._runtime_initializer = runtime_initializer
        self._model_loader = model_loader

    def create(
        self,
        *,
        model: str,
        device: str,
        compute_type: str,
        worker_count: int,
    ) -> WhisperModelProtocol:
        self._runtime_initializer.initialize()

        model_constructor = self._model_loader()

        return model_constructor(
            model,
            device=device,
            compute_type=compute_type,
            num_workers=worker_count,
        )
