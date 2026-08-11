from __future__ import annotations

import numpy as np
import soxr

from app.audio.contracts import Float32Audio
from app.audio.protocols import AudioResampler


class IdentityAudioResampler:
    """Pass audio through unchanged when no resampling is required."""

    def __init__(self, channels: int) -> None:
        self._channels = channels

    def process(self, audio: Float32Audio) -> Float32Audio:
        return audio

    def flush(self) -> Float32Audio:
        return np.empty(
            (0, self._channels),
            dtype=np.float32,
        )

    def reset(self) -> None:
        """Reset the resampler state."""


class SoXRResampler:
    """Streaming sample-rate converter backed by SoXR."""

    def __init__(
        self,
        input_sample_rate: int,
        output_sample_rate: int,
        channels: int,
    ) -> None:
        self._input_sample_rate = input_sample_rate
        self._output_sample_rate = output_sample_rate
        self._channels = channels

        self._stream = soxr.ResampleStream(
            input_sample_rate,
            output_sample_rate,
            channels,
            dtype="float32",
        )

    def process(self, audio: Float32Audio) -> Float32Audio:
        return self._stream.resample_chunk(audio, last=False)

    def flush(self) -> Float32Audio:
        return self._stream.resample_chunk(
            np.empty(
                (0, self._channels),
                dtype=np.float32,
            ),
            last=True,
        )

    def reset(self) -> None:
        self._stream = soxr.ResampleStream(
            self._input_sample_rate,
            self._output_sample_rate,
            self._channels,
            dtype="float32",
        )


class SoXRResamplerFactory:
    def create(
        self,
        input_sample_rate: int,
        output_sample_rate: int,
        channels: int,
    ) -> AudioResampler:
        return SoXRResampler(
            input_sample_rate=input_sample_rate,
            output_sample_rate=output_sample_rate,
            channels=channels,
        )
