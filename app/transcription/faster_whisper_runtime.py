from __future__ import annotations

import importlib
from collections.abc import Callable
from typing import Protocol, cast


class FasterWhisperRuntimeInitializer(Protocol):
    """Prepare the process runtime required before Faster-Whisper is imported."""

    def initialize(self) -> None:
        """Initialize the configured Faster-Whisper runtime."""


class _RocmSdkProtocol(Protocol):
    def initialize_process(
        self,
        *,
        preload_shortnames: list[str],
    ) -> None:
        """Initialize the process-wide ROCm runtime."""


type RocmSdkLoader = Callable[[], _RocmSdkProtocol]


def _load_rocm_sdk() -> _RocmSdkProtocol:
    module = importlib.import_module("rocm_sdk")
    return cast(_RocmSdkProtocol, module)


class DefaultFasterWhisperRuntimeInitializer:
    """Use the environment's default CTranslate2 runtime."""

    def initialize(self) -> None:
        pass


class TheRockFasterWhisperRuntimeInitializer:
    """Initialize TheRock before CTranslate2 native libraries are loaded."""

    _PRELOAD_SHORTNAMES = (
        "amd_comgr",
        "amdhip64",
        "hipblas",
        "hiprand",
    )

    def __init__(
        self,
        sdk_loader: RocmSdkLoader = _load_rocm_sdk,
    ) -> None:
        self._sdk_loader = sdk_loader
        self._initialized = False

    def initialize(self) -> None:
        if self._initialized:
            return

        sdk = self._sdk_loader()

        sdk.initialize_process(
            preload_shortnames=list(self._PRELOAD_SHORTNAMES),
        )

        self._initialized = True
