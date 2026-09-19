import pytest

from app.observability.hardware import (
    GraphicsAdapterInfo,
    GraphicsAdaptersObservation,
)


def test_unavailable_observation_requires_error() -> None:
    with pytest.raises(
        ValueError,
        match="must contain error information",
    ):
        GraphicsAdaptersObservation(
            available=False,
            adapters=(),
        )


def test_available_observation_serializes_adapters() -> None:
    observation = GraphicsAdaptersObservation.success(
        (
            GraphicsAdapterInfo(
                name="AMD Radeon RX 6800M",
                driver_version="1.2.3",
                pnp_device_id="PCI\\VEN_1002",
            ),
        )
    )

    assert observation.to_dict() == {
        "available": True,
        "adapters": [
            {
                "name": "AMD Radeon RX 6800M",
                "driver_version": "1.2.3",
                "pnp_device_id": "PCI\\VEN_1002",
            }
        ],
    }
