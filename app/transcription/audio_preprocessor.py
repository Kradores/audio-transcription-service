from __future__ import annotations

import logging

import numpy as np

from app.audio.contracts import SpeechSegment
from app.transcription.contracts import AudioSource

logger = logging.getLogger(__name__)


class IdentityTranscriptionAudioPreprocessor:
    """Pass transcription audio through unchanged."""

    def process(
        self,
        segment: SpeechSegment,
    ) -> SpeechSegment:
        return segment


class FixedGainTranscriptionAudioPreprocessor:
    """Apply deterministic gain to transcription audio."""

    def __init__(
        self,
        *,
        source: AudioSource,
        gain_db: float,
    ) -> None:
        self._source = source
        self._gain_db = gain_db
        self._linear_gain = 10 ** (gain_db / 20.0)

    def process(
        self,
        segment: SpeechSegment,
    ) -> SpeechSegment:
        amplified = segment.audio * self._linear_gain

        clipped_samples = int(
            np.count_nonzero(
                np.abs(amplified) > 1.0,
            )
        )

        audio = np.ascontiguousarray(
            np.clip(
                amplified,
                -1.0,
                1.0,
            ),
            dtype=np.float32,
        )

        if clipped_samples > 0:
            logger.warning(
                "transcription audio clipped "
                "source=%s gain_db=%.1f "
                "input_peak=%.3f clipped_samples=%d",
                self._source.value,
                self._gain_db,
                float(
                    np.max(
                        np.abs(segment.audio),
                    )
                ),
                clipped_samples,
            )

        return SpeechSegment(
            audio=audio,
            timestamp=segment.timestamp,
            duration=segment.duration,
            format=segment.format,
        )
