from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class GraphicsAdapterInfo:
    name: str
    driver_version: str | None
    pnp_device_id: str | None

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("graphics adapter name must not be empty")

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "driver_version": self.driver_version,
            "pnp_device_id": self.pnp_device_id,
        }


@dataclass(frozen=True, slots=True)
class GraphicsAdaptersObservation:
    available: bool
    adapters: tuple[GraphicsAdapterInfo, ...]
    error_type: str | None = None
    error: str | None = None

    def __post_init__(self) -> None:
        if self.available:
            if self.error_type is not None or self.error is not None:
                raise ValueError("available graphics observation must not contain an error")

            return

        if self.adapters:
            raise ValueError("unavailable graphics observation must not contain adapters")

        if not self.error_type or not self.error:
            raise ValueError("unavailable graphics observation must contain error information")

    @classmethod
    def success(
        cls,
        adapters: tuple[GraphicsAdapterInfo, ...],
    ) -> GraphicsAdaptersObservation:
        return cls(
            available=True,
            adapters=adapters,
        )

    @classmethod
    def failure(
        cls,
        *,
        error_type: str,
        error: str,
    ) -> GraphicsAdaptersObservation:
        return cls(
            available=False,
            adapters=(),
            error_type=error_type,
            error=error,
        )

    def to_dict(self) -> dict[str, object]:
        result: dict[str, object] = {
            "available": self.available,
            "adapters": [adapter.to_dict() for adapter in self.adapters],
        }

        if not self.available:
            result["error_type"] = self.error_type
            result["error"] = self.error

        return result
