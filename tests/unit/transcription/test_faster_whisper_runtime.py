from __future__ import annotations

import pytest

from app.transcription.faster_whisper_runtime import (
    DefaultFasterWhisperRuntimeInitializer,
    TheRockFasterWhisperRuntimeInitializer,
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


def test_default_runtime_initializer_does_nothing() -> None:
    initializer = DefaultFasterWhisperRuntimeInitializer()

    initializer.initialize()


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
