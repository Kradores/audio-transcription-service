from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

import numpy as np

from app.transcription.faster_whisper_factory import (
    FasterWhisperModelFactory,
)
from app.transcription.protocols import WhisperInfoProtocol, WhisperSegmentProtocol


class FakeRuntimeInitializer:
    def __init__(self, events: list[str]) -> None:
        self._events = events

    def initialize(self) -> None:
        self._events.append("runtime_initialized")


class FakeModel:
    def transcribe(
        self,
        audio: np.ndarray,
    ) -> tuple[Iterable[WhisperSegmentProtocol], WhisperInfoProtocol]:
        raise NotImplementedError


def test_factory_initializes_runtime_before_loading_model() -> None:
    events: list[str] = []

    runtime = FakeRuntimeInitializer(events)

    def load_model() -> Callable[..., FakeModel]:
        events.append("model_loaded")

        def create_model(
            model_size_or_path: str,
            *,
            device: str,
            compute_type: str,
            num_workers: int,
        ) -> FakeModel:
            events.append("model_created")
            return FakeModel()

        return create_model

    factory = FasterWhisperModelFactory(
        runtime_initializer=runtime,
        model_loader=load_model,
    )

    factory.create(
        model="small",
        device="cuda",
        compute_type="float16",
        worker_count=1,
    )

    assert events == [
        "runtime_initialized",
        "model_loaded",
        "model_created",
    ]


def test_factory_passes_model_configuration_to_whisper_model() -> None:
    captured: dict[str, Any] = {}

    class Runtime:
        def initialize(self) -> None:
            pass

    def load_model() -> Callable[..., FakeModel]:
        def create_model(
            model_size_or_path: str,
            *,
            device: str,
            compute_type: str,
            num_workers: int,
        ) -> FakeModel:
            captured.update(
                {
                    "model": model_size_or_path,
                    "device": device,
                    "compute_type": compute_type,
                    "num_workers": num_workers,
                }
            )
            return FakeModel()

        return create_model

    factory = FasterWhisperModelFactory(
        runtime_initializer=Runtime(),
        model_loader=load_model,
    )

    factory.create(
        model="small",
        device="cuda",
        compute_type="float16",
        worker_count=3,
    )

    assert captured == {
        "model": "small",
        "device": "cuda",
        "compute_type": "float16",
        "num_workers": 3,
    }


def test_factory_does_not_load_faster_whisper_during_construction() -> None:
    load_count = 0

    class Runtime:
        def initialize(self) -> None:
            pass

    def load_model() -> Callable[..., FakeModel]:
        nonlocal load_count
        load_count += 1
        raise AssertionError("model loader should not run")

    FasterWhisperModelFactory(
        runtime_initializer=Runtime(),
        model_loader=load_model,
    )

    assert load_count == 0


def test_factory_does_not_load_model_when_runtime_initialization_fails() -> None:
    load_count = 0

    class FailingRuntime:
        def initialize(self) -> None:
            raise RuntimeError("runtime failed")

    def load_model() -> Callable[..., FakeModel]:
        nonlocal load_count
        load_count += 1
        raise AssertionError("model loader must not run")

    factory = FasterWhisperModelFactory(
        runtime_initializer=FailingRuntime(),
        model_loader=load_model,
    )

    try:
        factory.create(
            model="small",
            device="cuda",
            compute_type="float16",
            worker_count=1,
        )
    except RuntimeError as exc:
        assert str(exc) == "runtime failed"

    assert load_count == 0
