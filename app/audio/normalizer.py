from __future__ import annotations

import numpy as np

from app.audio.contracts import (
    AudioFormat,
    AudioFrame,
    Float32Audio,
    Int16Audio,
    ProcessingAudioFrame,
)
from app.audio.protocols import AudioResampler, AudioResamplerFactory
from app.core.config.constants import PROCESSING_FRAME_DURATION_SECONDS
from app.core.config.models import AudioProcessingSettings


class AudioNormalizerImpl:
    """Normalize captured audio into fixed-size processing frames."""

    def __init__(
        self,
        settings: AudioProcessingSettings,
        resampler_factory: AudioResamplerFactory,
    ) -> None:
        self._resampler_factory = resampler_factory

        self._processing_format = AudioFormat(
            sample_rate=settings.sample_rate,
            channels=settings.channels,
            sample_type="float32",
        )
        self._processing_frame_samples = round(
            self._processing_format.sample_rate * PROCESSING_FRAME_DURATION_SECONDS,
        )
        self._buffer = np.empty(
            (0, self._processing_format.channels),
            dtype=np.float32,
        )

        self._resampler: AudioResampler | None = None
        self._input_sample_rate: int | None = None
        self._buffer_timestamp: float | None = None

    def process(
        self,
        frame: AudioFrame,
    ) -> tuple[ProcessingAudioFrame, ...]:
        self._ensure_resampler(frame)

        if self._resampler is not None and self._input_sample_rate != frame.format.sample_rate:
            raise ValueError("input sample rate changed during normalization")

        audio = (
            self._convert_channels(
                frame.audio,
                self._processing_format.channels,
            ).astype(np.float32)
            / 32768.0
        )

        resampler = self._get_resampler(frame.format.sample_rate)
        audio = resampler.process(audio)

        if self._buffer_timestamp is None:
            self._buffer_timestamp = frame.timestamp

        self._buffer = np.concatenate(
            (self._buffer, audio),
            axis=0,
        )

        return self._emit_complete_frames()

    def flush(self) -> tuple[ProcessingAudioFrame, ...]:
        if self._resampler is not None:
            resampled = self._resampler.flush()

            if resampled.size > 0:
                if self._buffer_timestamp is None:
                    # This should normally not happen if flush follows process(),
                    # but there is no timestamp available for resampler-only output.
                    raise RuntimeError(
                        "resampler produced output without buffered audio timestamp",
                    )

                self._buffer = np.concatenate(
                    (self._buffer, resampled),
                    axis=0,
                )

        output = self._emit_complete_frames()

        self._buffer = np.empty(
            (0, self._processing_format.channels),
            dtype=np.float32,
        )
        self._buffer_timestamp = None

        return output

    def reset(self) -> None:
        """Discard all buffered and resampler state."""

        self._buffer = np.empty(
            (0, self._processing_format.channels),
            dtype=np.float32,
        )
        self._buffer_timestamp = None

        if self._resampler is not None:
            self._resampler.reset()

        self._input_sample_rate = None

    def _ensure_resampler(self, frame: AudioFrame) -> None:
        input_sample_rate = frame.format.sample_rate

        if self._resampler is not None:
            if self._input_sample_rate == input_sample_rate:
                return

            self._resampler.reset()

        self._resampler = self._resampler_factory.create(
            input_sample_rate=input_sample_rate,
            output_sample_rate=self._processing_format.sample_rate,
            channels=self._processing_format.channels,
        )

        self._input_sample_rate = input_sample_rate

    def _get_resampler(
        self,
        input_sample_rate: int,
    ) -> AudioResampler:
        if self._resampler is None:
            self._resampler = self._resampler_factory.create(
                input_sample_rate=input_sample_rate,
                output_sample_rate=self._processing_format.sample_rate,
                channels=self._processing_format.channels,
            )

        return self._resampler

    @staticmethod
    def _convert_channels(
        audio: Int16Audio,
        target_channels: int,
    ) -> Float32Audio:
        if audio.shape[1] == target_channels:
            return audio.astype(np.float32)

        if target_channels == 1:
            return audio.astype(np.float32).mean(axis=1, keepdims=True)

        if target_channels == 2 and audio.shape[1] == 1:
            return np.repeat(audio, 2, axis=1).astype(np.float32)

        raise ValueError(f"unsupported channel conversion: {audio.shape[1]} -> {target_channels}")

    def _emit_complete_frames(
        self,
    ) -> tuple[ProcessingAudioFrame, ...]:
        if self._buffer_timestamp is None:
            return ()

        frame_count = self._buffer.shape[0] // self._processing_frame_samples

        if frame_count == 0:
            return ()

        sample_count = frame_count * self._processing_frame_samples

        complete_audio = self._buffer[:sample_count]
        self._buffer = self._buffer[sample_count:]

        timestamp = self._buffer_timestamp
        outputs: list[ProcessingAudioFrame] = []

        for index in range(frame_count):
            start = index * self._processing_frame_samples
            end = start + self._processing_frame_samples

            outputs.append(
                ProcessingAudioFrame(
                    audio=complete_audio[start:end],
                    timestamp=timestamp,
                    format=self._processing_format,
                ),
            )

            timestamp += self._processing_frame_samples / self._processing_format.sample_rate

        self._buffer_timestamp = timestamp if self._buffer.shape[0] > 0 else None

        return tuple(outputs)
