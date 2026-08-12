from typing import Any, TypedDict

class SileroVADEvent(TypedDict, total=False):
    start: int
    end: int

class VADIterator:
    def __init__(
        self,
        model: Any,
        threshold: float = ...,
        sampling_rate: int = ...,
        min_silence_duration_ms: int = ...,
        speech_pad_ms: int = ...,
    ) -> None: ...
    def __call__(
        self,
        audio: Any,
    ) -> dict[str, int | float] | None: ...
    def reset_states(self) -> None: ...

def load_silero_vad() -> Any: ...
