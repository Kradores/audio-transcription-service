from __future__ import annotations

import ctypes
import importlib
import logging
import os
from collections.abc import Callable
from pathlib import Path
from typing import Protocol, cast

logger = logging.getLogger(__name__)


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


class NvidiaFasterWhisperRuntimeInitializer:
    """Initialize private NVIDIA libraries before CTranslate2 is imported."""

    _PRELOAD_ORDER = (
        "cublasLt64_12.dll",
        "cublas64_12.dll",
        "nvrtc-builtins64_124.dll",
        "nvrtc64_120_0.dll",
        "cudnn_graph64_9.dll",
        "cudnn_ops64_9.dll",
        "cudnn_adv64_9.dll",
        "cudnn_cnn64_9.dll",
        "cudnn_heuristic64_9.dll",
        "cudnn_engines_precompiled64_9.dll",
        "cudnn_engines_runtime_compiled64_9.dll",
        "cudnn64_9.dll",
    )

    def __init__(
        self,
        *,
        runtime_directory: Path,
    ) -> None:
        self._runtime_directory = runtime_directory
        self._initialized = False
        self._dll_directory_handle: object | None = None
        self._loaded_libraries: list[ctypes.CDLL] = []

    def initialize(self) -> None:
        if self._initialized:
            return

        if os.name != "nt":
            raise RuntimeError("NVIDIA Faster-Whisper runtime is supported on Windows only")

        runtime_directory = self._runtime_directory.resolve()

        if not runtime_directory.is_dir():
            raise RuntimeError(f"NVIDIA runtime directory does not exist: {runtime_directory}")

        missing = [name for name in self._PRELOAD_ORDER if not (runtime_directory / name).is_file()]

        if missing:
            raise RuntimeError("NVIDIA runtime is incomplete; missing DLLs: " + ", ".join(missing))

        dll_directory_handle = os.add_dll_directory(
            str(runtime_directory),
        )

        loaded_libraries: list[ctypes.CDLL] = []

        try:
            for name in self._PRELOAD_ORDER:
                path = runtime_directory / name

                loaded_libraries.append(ctypes.WinDLL(str(path)))
        except Exception:
            dll_directory_handle.close()
            raise

        self._dll_directory_handle = dll_directory_handle
        self._loaded_libraries = loaded_libraries
        self._initialized = True

        logger.info(
            "NVIDIA Faster-Whisper runtime initialized runtime_directory=%s libraries=%d",
            runtime_directory,
            len(loaded_libraries),
        )
