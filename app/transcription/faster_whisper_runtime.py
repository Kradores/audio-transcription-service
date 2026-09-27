from __future__ import annotations

from typing import Protocol

from app.core.config.enums import WhisperRuntime


class FasterWhisperRuntimeInitializer(Protocol):
    """Prepare the process runtime required before Faster-Whisper is imported."""

    def initialize(self) -> None:
        """Initialize the runtime before loading Faster-Whisper."""


class FasterWhisperRuntimeInitializerFactory(Protocol):
    def create(
        self,
        runtime: WhisperRuntime,
    ) -> FasterWhisperRuntimeInitializer:
        """Create the runtime initializer for the configured runtime."""


class DefaultFasterWhisperRuntimeInitializer:
    """Use the environment's default CTranslate2 runtime."""

    def initialize(self) -> None:
        pass


class DefaultFasterWhisperRuntimeInitializerFactory:
    def create(
        self,
        runtime: WhisperRuntime,
    ) -> FasterWhisperRuntimeInitializer:
        if runtime is not WhisperRuntime.DEFAULT:
            raise ValueError(
                f"Runtime '{runtime.value}' is not supported by "
                "the default runtime initializer factory"
            )

        return DefaultFasterWhisperRuntimeInitializer()
