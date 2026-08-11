from __future__ import annotations

import numpy as np

from app.audio.contracts import (
    PROCESSING_FRAME_DURATION_SECONDS,
    AudioFormat,
    AudioFrame,
    ProcessingAudioFrame,
)
from app.core.config.models import AudioProcessingSettings


class AudioNormalizerImpl:
    """Normalize captured audio into fixed-size processing frames."""

    def __init__(self, settings: AudioProcessingSettings) -> None:
        self._settings = settings
        self._processing_format = AudioFormat(
            sample_rate=settings.sample_rate,
            channels=settings.channels,
            sample_type="float32",
        )
        self._processing_frame_samples = round(
            self._processing_format.sample_rate * PROCESSING_FRAME_DURATION_SECONDS,
        )
        self._buffer = np.empty(
            (0, self._settings.channels),
            dtype=np.float32,
        )
        self._buffer_timestamp: float | None = None

    def process(
        self,
        frame: AudioFrame,
    ) -> tuple[ProcessingAudioFrame, ...]:
        self._validate_format(frame)

        audio = (
            self._convert_channels(frame.audio, self._settings.channels).astype(np.float32)
            / 32768.0
        )

        if self._buffer_timestamp is None:
            self._buffer_timestamp = frame.timestamp

        self._buffer = np.concatenate(
            (self._buffer, audio),
            axis=0,
        )

        return self._emit_complete_frames()

    def flush(self) -> None:
        self._buffer = np.empty(
            (0, self._settings.channels),
            dtype=np.float32,
        )
        self._buffer_timestamp = None

    def _validate_format(self, frame: AudioFrame) -> None:
        if frame.format.sample_rate != self._processing_format.sample_rate:
            raise ValueError(
                "AudioNormalizer currently requires a "
                f"{self._processing_format.sample_rate} Hz input sample rate"
            )

    @staticmethod
    def _convert_channels(
        audio: np.ndarray,
        target_channels: int,
    ) -> np.ndarray:
        if audio.shape[1] == target_channels:
            return audio

        if target_channels == 1:
            return audio.astype(np.float32).mean(axis=1, keepdims=True)

        if target_channels == 2 and audio.shape[1] == 1:
            return np.repeat(audio, 2, axis=1)

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
