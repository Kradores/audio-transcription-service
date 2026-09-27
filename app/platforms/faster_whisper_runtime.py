from __future__ import annotations

import sys

from app.transcription.faster_whisper_runtime import (
    DefaultFasterWhisperRuntimeInitializerFactory,
    FasterWhisperRuntimeInitializerFactory,
)


def create_platform_runtime_initializer_factory() -> FasterWhisperRuntimeInitializerFactory:
    if sys.platform == "win32":
        from app.platforms.windows.faster_whisper_runtime import (
            WindowsFasterWhisperRuntimeInitializerFactory,
        )

        return WindowsFasterWhisperRuntimeInitializerFactory()

    return DefaultFasterWhisperRuntimeInitializerFactory()
