from collections.abc import Callable
from typing import Any

paInt16: int
paContinue: int
paComplete: int
paAbort: int

class Stream:
    def start_stream(self) -> None: ...
    def stop_stream(self) -> None: ...
    def close(self) -> None: ...

class PyAudio:
    def get_default_wasapi_loopback(self) -> dict[str, Any]: ...
    def open(
        self,
        *,
        rate: int,
        channels: int,
        format: int,
        input: bool = ...,
        output: bool = ...,
        input_device_index: int | None = ...,
        frames_per_buffer: int = ...,
        start: bool = ...,
        stream_callback: Callable[..., tuple[None, int]] | None = ...,
    ) -> Stream: ...
    def terminate(self) -> None: ...
