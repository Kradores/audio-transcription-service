from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
from numpy.typing import NDArray

from app.core.config.constants import PROCESSING_FRAME_DURATION_SECONDS

type Float32Audio = NDArray[np.float32]
type Int16Audio = NDArray[np.int16]

type AudioSampleType = Literal["int16", "float32"]


@dataclass(frozen=True, slots=True)
class AudioFormat:
    """Describes the representation of audio samples."""

    sample_rate: int
    channels: int
    sample_type: AudioSampleType

    def __post_init__(self) -> None:
        if self.sample_rate <= 0:
            raise ValueError("sample_rate must be positive")

        if self.channels <= 0 or self.channels > 2:
            raise ValueError("channels must be between 1 and 2")

        if self.sample_type not in ("int16", "float32"):
            raise ValueError("sample_type must be either 'int16' or 'float32'")


@dataclass(frozen=True, slots=True)
class AudioFrame:
    """Audio acquired from the capture layer in its native format."""

    audio: Int16Audio
    timestamp: float
    format: AudioFormat

    def __post_init__(self) -> None:
        if self.timestamp < 0:
            raise ValueError("timestamp must not be negative")

        if self.audio.ndim != 2:
            raise ValueError("audio must have shape (samples, channels)")

        if self.audio.shape[1] != self.format.channels:
            raise ValueError("audio channel count must match format.channels")

        if self.format.sample_type != "int16":
            raise ValueError("capture audio must use int16 samples")


@dataclass(frozen=True, slots=True)
class ProcessingAudioFrame:
    """Exactly 20 ms of normalized audio."""

    audio: Float32Audio
    timestamp: float
    format: AudioFormat

    def __post_init__(self) -> None:
        if self.timestamp < 0:
            raise ValueError("timestamp must not be negative")

        if self.audio.ndim != 2:
            raise ValueError("audio must have shape (samples, channels)")

        if self.audio.shape[1] != self.format.channels:
            raise ValueError("audio channel count must match format.channels")

        if self.format.sample_type != "float32":
            raise ValueError("processing audio must use float32 samples")

        expected_samples = round(
            self.format.sample_rate * PROCESSING_FRAME_DURATION_SECONDS,
        )

        if self.audio.shape[0] != expected_samples:
            raise ValueError(
                "processing audio must contain exactly 20 ms of audio",
            )


@dataclass(frozen=True, slots=True)
class SpeechStart:
    """Indicates that speech has started."""

    timestamp: float

    def __post_init__(self) -> None:
        if self.timestamp < 0:
            raise ValueError("timestamp must not be negative")


@dataclass(frozen=True, slots=True)
class SpeechEnd:
    """Indicates that speech has ended."""

    timestamp: float

    def __post_init__(self) -> None:
        if self.timestamp < 0:
            raise ValueError("timestamp must not be negative")


@dataclass(frozen=True, slots=True)
class SpeechSegment:
    """Normalized speech audio ready for transcription."""

    audio: Float32Audio
    timestamp: float
    duration: float
    format: AudioFormat

    def __post_init__(self) -> None:
        if self.timestamp < 0:
            raise ValueError("timestamp must not be negative")

        if self.duration < 0:
            raise ValueError("duration must not be negative")

        if self.audio.ndim != 2:
            raise ValueError("audio must have shape (samples, channels)")

        if self.audio.shape[1] != self.format.channels:
            raise ValueError("speech segments must contain mono audio")

        expected_duration = self.audio.shape[0] / self.format.sample_rate

        if not np.isclose(self.duration, expected_duration):
            raise ValueError("duration must match the audio sample count")

        owned_audio = np.array(
            self.audio,
            dtype=np.float32,
            copy=True,
        )
        owned_audio.setflags(write=False)

        object.__setattr__(self, "audio", owned_audio)
