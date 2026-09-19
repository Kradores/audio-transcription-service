from __future__ import annotations

from dataclasses import dataclass

from app.core.config.enums import (
    WhisperComputeType,
    WhisperDevice,
    WhisperRuntime,
)


@dataclass(frozen=True, slots=True)
class CTranslate2CapabilitiesObservation:
    available: bool
    cuda_device_count: int | None
    supported_compute_types: tuple[str, ...]
    error_type: str | None = None
    error: str | None = None

    def __post_init__(self) -> None:
        if self.available:
            if self.error_type is not None or self.error is not None:
                raise ValueError("available CTranslate2 observation must not contain an error")

            return

        if self.cuda_device_count is not None:
            raise ValueError(
                "unavailable CTranslate2 observation must not contain a CUDA device count"
            )

        if self.supported_compute_types:
            raise ValueError(
                "unavailable CTranslate2 observation must not contain supported compute types"
            )

        if not self.error_type or not self.error:
            raise ValueError("unavailable CTranslate2 observation must contain error information")

    @classmethod
    def success(
        cls,
        *,
        cuda_device_count: int | None,
        supported_compute_types: tuple[str, ...],
    ) -> CTranslate2CapabilitiesObservation:
        return cls(
            available=True,
            cuda_device_count=cuda_device_count,
            supported_compute_types=supported_compute_types,
        )

    @classmethod
    def failure(
        cls,
        *,
        error_type: str,
        error: str,
    ) -> CTranslate2CapabilitiesObservation:
        return cls(
            available=False,
            cuda_device_count=None,
            supported_compute_types=(),
            error_type=error_type,
            error=error,
        )

    def to_dict(self) -> dict[str, object]:
        result: dict[str, object] = {
            "available": self.available,
            "cuda_device_count": self.cuda_device_count,
            "supported_compute_types": list(
                self.supported_compute_types,
            ),
        }

        if not self.available:
            result["error_type"] = self.error_type
            result["error"] = self.error

        return result


@dataclass(frozen=True, slots=True)
class TranscriptionRuntimeObservation:
    runtime: WhisperRuntime
    device: WhisperDevice
    configured_compute_type: WhisperComputeType
    initialized: bool
    ctranslate2: CTranslate2CapabilitiesObservation

    def to_dict(self) -> dict[str, object]:
        return {
            "runtime": self.runtime.value,
            "device": self.device.value,
            "configured_compute_type": (self.configured_compute_type.value),
            "initialized": self.initialized,
            "ctranslate2": self.ctranslate2.to_dict(),
        }
