from app.core.config.enums import (
    WhisperComputeType,
    WhisperDevice,
    WhisperRuntime,
)
from app.observability.transcription_runtime import (
    CTranslate2CapabilitiesObservation,
    TranscriptionRuntimeObservation,
)


def test_transcription_runtime_observation_serializes() -> None:
    observation = TranscriptionRuntimeObservation(
        runtime=WhisperRuntime.THEROCK,
        device=WhisperDevice.CUDA,
        configured_compute_type=(WhisperComputeType.FLOAT16),
        initialized=True,
        ctranslate2=(
            CTranslate2CapabilitiesObservation.success(
                cuda_device_count=1,
                supported_compute_types=(
                    "float16",
                    "float32",
                ),
            )
        ),
    )

    assert observation.to_dict() == {
        "runtime": "therock",
        "device": "cuda",
        "configured_compute_type": "float16",
        "initialized": True,
        "ctranslate2": {
            "available": True,
            "cuda_device_count": 1,
            "supported_compute_types": [
                "float16",
                "float32",
            ],
        },
    }
