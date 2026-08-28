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
    def is_active(self) -> bool: ...

class PyAudio:
    def get_default_wasapi_loopback(self) -> dict[str, Any]: ...
    def get_default_input_device_info(self) -> dict[str, Any]: ...
    def get_default_wasapi_device(self, *, d_out: bool = False, d_in: bool = False) -> dict: ...
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
