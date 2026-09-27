from __future__ import annotations

from app.transcription.faster_whisper_runtime import (
    DefaultFasterWhisperRuntimeInitializer,
)


def test_default_runtime_initializer_does_nothing() -> None:
    initializer = DefaultFasterWhisperRuntimeInitializer()

    initializer.initialize()
