import numpy as np

class ResampleStream:
    def __init__(
        self,
        input_sample_rate: int,
        output_sample_rate: int,
        channels: int,
        dtype: str = "float32",
    ) -> None: ...
    def resample_chunk(
        self,
        audio_chunk: np.ndarray,
        last: bool = False,
    ) -> np.ndarray: ...
