from __future__ import annotations

import importlib
from collections.abc import Callable
from typing import Protocol, cast

from app.core.config.enums import (
    WhisperComputeType,
    WhisperDevice,
    WhisperRuntime,
)
from app.observability.transcription_runtime import (
    CTranslate2CapabilitiesObservation,
    TranscriptionRuntimeObservation,
)

_MAX_ERROR_LENGTH = 1000


class _CTranslate2Api(Protocol):
    def get_cuda_device_count(self) -> int:
        """Return visible accelerator devices."""

    def get_supported_compute_types(
        self,
        device: str,
        device_index: int = 0,
    ) -> set[str]:
        """Return supported compute types."""


type CTranslate2ApiLoader = Callable[[], _CTranslate2Api]


def _load_ctranslate2_api() -> _CTranslate2Api:
    module = importlib.import_module(
        "ctranslate2",
    )

    return cast(
        _CTranslate2Api,
        module,
    )


class CTranslate2RuntimeObserver:
    """Observe capabilities of an initialized CTranslate2 runtime."""

    def __init__(
        self,
        api_loader: CTranslate2ApiLoader = (_load_ctranslate2_api),
    ) -> None:
        self._api_loader = api_loader

    def observe(
        self,
        *,
        runtime: WhisperRuntime,
        device: WhisperDevice,
        compute_type: WhisperComputeType,
    ) -> TranscriptionRuntimeObservation:
        capabilities = self._observe_capabilities(
            device,
        )

        return TranscriptionRuntimeObservation(
            runtime=runtime,
            device=device,
            configured_compute_type=compute_type,
            initialized=True,
            ctranslate2=capabilities,
        )

    def _observe_capabilities(
        self,
        device: WhisperDevice,
    ) -> CTranslate2CapabilitiesObservation:
        if device is WhisperDevice.AUTO:
            return CTranslate2CapabilitiesObservation.failure(
                error_type="UnsupportedConfiguredDevice",
                error=(
                    "CTranslate2 capability observation requires an explicit cpu or cuda device."
                ),
            )

        try:
            api = self._api_loader()

            if device is WhisperDevice.CPU:
                supported_compute_types = api.get_supported_compute_types(
                    "cpu",
                    0,
                )

                cuda_device_count: int | None = None

            else:
                cuda_device_count = api.get_cuda_device_count()

                if cuda_device_count < 0:
                    raise ValueError("CTranslate2 returned a negative CUDA device count")

                supported_compute_types = api.get_supported_compute_types(
                    "cuda",
                    0,
                )

        except Exception as exc:
            return CTranslate2CapabilitiesObservation.failure(
                error_type=type(exc).__name__,
                error=_bounded_error(
                    str(exc),
                ),
            )

        return CTranslate2CapabilitiesObservation.success(
            cuda_device_count=cuda_device_count,
            supported_compute_types=tuple(
                sorted(
                    supported_compute_types,
                )
            ),
        )


def _bounded_error(
    value: str,
) -> str:
    value = " ".join(value.split())

    if not value:
        return "Unknown CTranslate2 observation error."

    return value[:_MAX_ERROR_LENGTH]
