from __future__ import annotations

from app.core.config.enums import (
    WhisperComputeType,
    WhisperDevice,
    WhisperRuntime,
)
from app.observability.ctranslate2_runtime import (
    CTranslate2RuntimeObserver,
)


class StubCTranslate2Api:
    def __init__(
        self,
        *,
        cuda_device_count: int = 0,
        supported_compute_types: set[str] | None = None,
    ) -> None:
        self.cuda_device_count = cuda_device_count

        self.supported_compute_types = supported_compute_types or {
            "float32",
        }

        self.cuda_device_count_calls = 0
        self.supported_device_calls: list[tuple[str, int]] = []

    def get_cuda_device_count(self) -> int:
        self.cuda_device_count_calls += 1

        return self.cuda_device_count

    def get_supported_compute_types(
        self,
        device: str,
        device_index: int = 0,
    ) -> set[str]:
        self.supported_device_calls.append(
            (
                device,
                device_index,
            )
        )

        return set(
            self.supported_compute_types,
        )


def test_observes_cpu_capabilities() -> None:
    api = StubCTranslate2Api(
        supported_compute_types={
            "int8",
            "float32",
            "int8_float32",
        },
    )

    result = CTranslate2RuntimeObserver(
        api_loader=lambda: api,
    ).observe(
        runtime=WhisperRuntime.DEFAULT,
        device=WhisperDevice.CPU,
        compute_type=WhisperComputeType.INT8,
    )

    assert result.initialized is True
    assert result.runtime is WhisperRuntime.DEFAULT
    assert result.device is WhisperDevice.CPU

    capabilities = result.ctranslate2

    assert capabilities.available is True
    assert capabilities.cuda_device_count is None

    assert capabilities.supported_compute_types == (
        "float32",
        "int8",
        "int8_float32",
    )

    assert api.cuda_device_count_calls == 0

    assert api.supported_device_calls == [
        (
            "cpu",
            0,
        )
    ]


def test_observes_cuda_capabilities() -> None:
    api = StubCTranslate2Api(
        cuda_device_count=1,
        supported_compute_types={
            "float32",
            "float16",
            "int8",
            "int8_float16",
        },
    )

    result = CTranslate2RuntimeObserver(
        api_loader=lambda: api,
    ).observe(
        runtime=WhisperRuntime.THEROCK,
        device=WhisperDevice.CUDA,
        compute_type=WhisperComputeType.FLOAT16,
    )

    capabilities = result.ctranslate2

    assert capabilities.available is True
    assert capabilities.cuda_device_count == 1

    assert capabilities.supported_compute_types == (
        "float16",
        "float32",
        "int8",
        "int8_float16",
    )

    assert api.cuda_device_count_calls == 1

    assert api.supported_device_calls == [
        (
            "cuda",
            0,
        )
    ]


def test_auto_device_is_reported_without_guessing() -> None:
    loader_called = False

    def load_api() -> StubCTranslate2Api:
        nonlocal loader_called
        loader_called = True

        return StubCTranslate2Api()

    result = CTranslate2RuntimeObserver(
        api_loader=load_api,
    ).observe(
        runtime=WhisperRuntime.DEFAULT,
        device=WhisperDevice.AUTO,
        compute_type=WhisperComputeType.DEFAULT,
    )

    assert result.initialized is True
    assert result.ctranslate2.available is False
    assert result.ctranslate2.error_type == ("UnsupportedConfiguredDevice")

    assert loader_called is False


def test_import_failure_is_diagnostic_only() -> None:
    def load_api() -> StubCTranslate2Api:
        raise ImportError(
            "ctranslate2 unavailable",
        )

    result = CTranslate2RuntimeObserver(
        api_loader=load_api,
    ).observe(
        runtime=WhisperRuntime.DEFAULT,
        device=WhisperDevice.CPU,
        compute_type=WhisperComputeType.INT8,
    )

    assert result.initialized is True
    assert result.ctranslate2.available is False
    assert result.ctranslate2.error_type == "ImportError"
    assert result.ctranslate2.error == ("ctranslate2 unavailable")


def test_capability_query_failure_is_diagnostic_only() -> None:
    class FailingApi(StubCTranslate2Api):
        def get_supported_compute_types(
            self,
            device: str,
            device_index: int = 0,
        ) -> set[str]:
            del device
            del device_index

            raise RuntimeError(
                "capability query failed",
            )

    result = CTranslate2RuntimeObserver(
        api_loader=lambda: FailingApi(),
    ).observe(
        runtime=WhisperRuntime.NVIDIA,
        device=WhisperDevice.CUDA,
        compute_type=WhisperComputeType.FLOAT16,
    )

    assert result.initialized is True
    assert result.ctranslate2.available is False
    assert result.ctranslate2.error_type == "RuntimeError"
    assert result.ctranslate2.error == ("capability query failed")
