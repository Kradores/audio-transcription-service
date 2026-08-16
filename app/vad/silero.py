from __future__ import annotations

import numpy as np

from app.audio.contracts import AudioSampleType, ProcessingAudioFrame, SpeechEnd, SpeechStart
from app.vad.protocols import SileroVADIterator


class SileroVADAdapter:
    """Adapt the Silero streaming VAD to the application VAD contract."""

    _SUPPORTED_SAMPLE_RATE = 16_000
    _SUPPORTED_CHANNELS = 1
    _SUPPORTED_SAMPLE_TYPE: AudioSampleType = "float32"
    _SILERO_WINDOW_SAMPLES = 512

    def __init__(self, iterator: SileroVADIterator) -> None:
        self._iterator = iterator
        self._audio_buffer = np.empty(0, dtype=np.float32)

    def process(
        self,
        frame: ProcessingAudioFrame,
    ) -> tuple[SpeechStart | SpeechEnd, ...]:
        self._validate_frame(frame)

        audio = np.asarray(
            frame.audio[:, 0],
            dtype=np.float32,
        )

        self._audio_buffer = np.concatenate(
            (self._audio_buffer, audio),
        )

        if self._audio_buffer.size < self._SILERO_WINDOW_SAMPLES:
            return ()

        window = self._audio_buffer[: self._SILERO_WINDOW_SAMPLES]
        self._audio_buffer = self._audio_buffer[self._SILERO_WINDOW_SAMPLES :].copy()

        event = self._iterator(window)

        if event is None:
            return ()

        if "start" in event:
            return (SpeechStart(timestamp=frame.timestamp),)

        if "end" in event:
            return (SpeechEnd(timestamp=frame.timestamp),)

        raise ValueError(f"unexpected Silero VAD event: {event!r}")

    def reset(self) -> None:
        """Reset the underlying Silero VAD state and pending audio."""

        self._iterator.reset_states()
        self._audio_buffer = np.empty(0, dtype=np.float32)

    @classmethod
    def _validate_frame(cls, frame: ProcessingAudioFrame) -> None:
        if frame.format.sample_rate != cls._SUPPORTED_SAMPLE_RATE:
            raise ValueError(
                "Silero VAD requires a 16 kHz processing sample rate",
            )

        if frame.format.channels != cls._SUPPORTED_CHANNELS:
            raise ValueError(
                "Silero VAD requires mono processing audio",
            )

        if frame.format.sample_type != cls._SUPPORTED_SAMPLE_TYPE:
            raise ValueError(
                "Silero VAD requires float32 processing audio",
            )
