import ctypes
import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.core.config.enums import WhisperRuntime
from app.platforms.windows.faster_whisper_runtime import (
    NvidiaFasterWhisperRuntimeInitializer,
    TheRockFasterWhisperRuntimeInitializer,
    WindowsFasterWhisperRuntimeInitializerFactory,
)
from app.transcription.faster_whisper_runtime import (
    DefaultFasterWhisperRuntimeInitializer,
    FasterWhisperRuntimeInitializer,
    FasterWhisperRuntimeInitializerFactory,
)


class FakeRocmSdk:
    def __init__(self) -> None:
        self.initialize_calls: list[list[str]] = []

    def initialize_process(
        self,
        *,
        preload_shortnames: list[str],
    ) -> None:
        self.initialize_calls.append(preload_shortnames)


def _create_complete_nvidia_runtime(
    tmp_path: Path,
) -> Path:
    runtime_directory = tmp_path / "nvidia-runtime"
    runtime_directory.mkdir()

    for name in NvidiaFasterWhisperRuntimeInitializer._PRELOAD_ORDER:
        (runtime_directory / name).touch()

    return runtime_directory


def _create_runtime_initializer_factory() -> tuple[
    MagicMock,
    MagicMock,
]:
    initializer = MagicMock(
        spec=FasterWhisperRuntimeInitializer,
    )

    factory = MagicMock(
        spec=FasterWhisperRuntimeInitializerFactory,
    )
    factory.create.return_value = initializer

    return factory, initializer


def test_nvidia_runtime_initializes_required_libraries_in_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime_directory = _create_complete_nvidia_runtime(
        tmp_path,
    )

    initializer = NvidiaFasterWhisperRuntimeInitializer(
        runtime_directory=runtime_directory,
    )

    loaded: list[str] = []

    monkeypatch.setattr(
        os,
        "name",
        "nt",
    )

    dll_handle = MagicMock()

    monkeypatch.setattr(
        os,
        "add_dll_directory",
        lambda path: dll_handle,
    )

    def load_library(path: str) -> MagicMock:
        loaded.append(
            Path(path).name,
        )
        return MagicMock()

    monkeypatch.setattr(
        ctypes,
        "WinDLL",
        load_library,
    )

    initializer.initialize()

    assert loaded == list(initializer._PRELOAD_ORDER)


def test_nvidia_runtime_initializes_only_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime_directory = _create_complete_nvidia_runtime(
        tmp_path,
    )

    dll_directory_handle = MagicMock()

    add_dll_directory = MagicMock(
        return_value=dll_directory_handle,
    )
    load_library = MagicMock(
        return_value=MagicMock(),
    )

    monkeypatch.setattr(
        os,
        "name",
        "nt",
    )
    monkeypatch.setattr(
        os,
        "add_dll_directory",
        add_dll_directory,
    )
    monkeypatch.setattr(
        ctypes,
        "WinDLL",
        load_library,
    )

    initializer = NvidiaFasterWhisperRuntimeInitializer(
        runtime_directory=runtime_directory,
    )

    initializer.initialize()
    initializer.initialize()

    add_dll_directory.assert_called_once_with(
        str(runtime_directory.resolve()),
    )

    assert load_library.call_count == len(initializer._PRELOAD_ORDER)

    dll_directory_handle.close.assert_not_called()


def test_nvidia_runtime_fails_when_runtime_directory_is_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime_directory = tmp_path / "missing-nvidia-runtime"

    monkeypatch.setattr(
        os,
        "name",
        "nt",
    )

    initializer = NvidiaFasterWhisperRuntimeInitializer(
        runtime_directory=runtime_directory,
    )

    with pytest.raises(
        RuntimeError,
        match="NVIDIA runtime directory does not exist",
    ):
        initializer.initialize()


def test_nvidia_runtime_reports_missing_dlls(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime_directory = _create_complete_nvidia_runtime(
        tmp_path,
    )

    missing_dlls = (
        "cublas64_12.dll",
        "cudnn64_9.dll",
    )

    for name in missing_dlls:
        (runtime_directory / name).unlink()

    monkeypatch.setattr(
        os,
        "name",
        "nt",
    )

    initializer = NvidiaFasterWhisperRuntimeInitializer(
        runtime_directory=runtime_directory,
    )

    with pytest.raises(RuntimeError) as exc_info:
        initializer.initialize()

    message = str(exc_info.value)

    assert "NVIDIA runtime is incomplete" in message
    assert "cublas64_12.dll" in message
    assert "cudnn64_9.dll" in message


def test_nvidia_runtime_can_retry_after_failed_initialization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime_directory = _create_complete_nvidia_runtime(
        tmp_path,
    )

    first_dll_directory_handle = MagicMock()
    second_dll_directory_handle = MagicMock()

    add_dll_directory = MagicMock(
        side_effect=[
            first_dll_directory_handle,
            second_dll_directory_handle,
        ]
    )

    load_attempts = 0

    def load_library(
        path: str,
    ) -> MagicMock:
        nonlocal load_attempts

        load_attempts += 1

        if load_attempts == 1:
            raise RuntimeError("NVIDIA DLL initialization failed")

        return MagicMock()

    monkeypatch.setattr(
        os,
        "name",
        "nt",
    )
    monkeypatch.setattr(
        os,
        "add_dll_directory",
        add_dll_directory,
    )
    monkeypatch.setattr(
        ctypes,
        "WinDLL",
        load_library,
    )

    initializer = NvidiaFasterWhisperRuntimeInitializer(
        runtime_directory=runtime_directory,
    )

    with pytest.raises(
        RuntimeError,
        match="NVIDIA DLL initialization failed",
    ):
        initializer.initialize()

    initializer.initialize()

    assert add_dll_directory.call_count == 2

    first_dll_directory_handle.close.assert_called_once_with()
    second_dll_directory_handle.close.assert_not_called()

    assert load_attempts == (1 + len(initializer._PRELOAD_ORDER))


def test_therock_runtime_initializes_required_libraries() -> None:
    sdk = FakeRocmSdk()
    initializer = TheRockFasterWhisperRuntimeInitializer(
        sdk_loader=lambda: sdk,
    )

    initializer.initialize()

    assert sdk.initialize_calls == [
        [
            "amd_comgr",
            "amdhip64",
            "hipblas",
            "hiprand",
        ]
    ]


def test_therock_runtime_initializes_only_once() -> None:
    sdk = FakeRocmSdk()
    initializer = TheRockFasterWhisperRuntimeInitializer(
        sdk_loader=lambda: sdk,
    )

    initializer.initialize()
    initializer.initialize()

    assert len(sdk.initialize_calls) == 1


def test_therock_runtime_can_retry_after_failed_initialization() -> None:
    attempts = 0

    class FailingOnceRocmSdk(FakeRocmSdk):
        def initialize_process(
            self,
            *,
            preload_shortnames: list[str],
        ) -> None:
            nonlocal attempts
            attempts += 1

            if attempts == 1:
                raise RuntimeError("ROCm initialization failed")

            super().initialize_process(
                preload_shortnames=preload_shortnames,
            )

    sdk = FailingOnceRocmSdk()
    initializer = TheRockFasterWhisperRuntimeInitializer(
        sdk_loader=lambda: sdk,
    )

    with pytest.raises(
        RuntimeError,
        match="ROCm initialization failed",
    ):
        initializer.initialize()

    initializer.initialize()

    assert attempts == 2
    assert len(sdk.initialize_calls) == 1


def test_therock_runtime_does_not_load_sdk_during_construction() -> None:
    load_count = 0

    def load_sdk() -> FakeRocmSdk:
        nonlocal load_count
        load_count += 1
        return FakeRocmSdk()

    TheRockFasterWhisperRuntimeInitializer(
        sdk_loader=load_sdk,
    )

    assert load_count == 0


@pytest.mark.parametrize(
    ("runtime", "expected_type"),
    [
        (
            WhisperRuntime.DEFAULT,
            DefaultFasterWhisperRuntimeInitializer,
        ),
        (
            WhisperRuntime.THEROCK,
            TheRockFasterWhisperRuntimeInitializer,
        ),
    ],
)
def test_factory_selects_configured_runtime(
    runtime: WhisperRuntime,
    expected_type: type[FasterWhisperRuntimeInitializer],
) -> None:
    factory = WindowsFasterWhisperRuntimeInitializerFactory()

    initializer = factory.create(runtime)

    assert isinstance(initializer, expected_type)


def test_factory_creates_nvidia_runtime_with_runtime_directory(
    tmp_path: Path,
) -> None:
    factory = WindowsFasterWhisperRuntimeInitializerFactory(
        nvidia_runtime_directory=tmp_path,
    )

    initializer = factory.create(
        WhisperRuntime.NVIDIA,
    )

    assert isinstance(
        initializer,
        NvidiaFasterWhisperRuntimeInitializer,
    )


def test_factory_rejects_nvidia_without_runtime_directory() -> None:
    factory = WindowsFasterWhisperRuntimeInitializerFactory()

    with pytest.raises(
        ValueError,
        match="requires nvidia_runtime_directory",
    ):
        factory.create(
            WhisperRuntime.NVIDIA,
        )


def test_factory_creates_therock_runtime_with_runtime_directory(
    tmp_path: Path,
) -> None:
    factory = WindowsFasterWhisperRuntimeInitializerFactory(
        nvidia_runtime_directory=None,
    )

    initializer = factory.create(
        WhisperRuntime.THEROCK,
    )

    assert isinstance(
        initializer,
        TheRockFasterWhisperRuntimeInitializer,
    )


def test_factory_creates_nvidia_runtime_with_configured_directory(
    tmp_path: Path,
) -> None:
    factory = WindowsFasterWhisperRuntimeInitializerFactory(
        nvidia_runtime_directory=tmp_path,
    )

    initializer = factory.create(
        WhisperRuntime.NVIDIA,
    )

    assert isinstance(
        initializer,
        NvidiaFasterWhisperRuntimeInitializer,
    )


def test_factory_passes_runtime_directory_to_nvidia_initializer(
    tmp_path: Path,
) -> None:
    factory = WindowsFasterWhisperRuntimeInitializerFactory(
        nvidia_runtime_directory=tmp_path,
    )

    initializer = factory.create(
        WhisperRuntime.NVIDIA,
    )

    assert isinstance(
        initializer,
        NvidiaFasterWhisperRuntimeInitializer,
    )
    assert initializer._runtime_directory == tmp_path
