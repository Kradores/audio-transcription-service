from __future__ import annotations

import math

import numpy as np

from app.audio.contracts import SpeechSegment
from app.core.config.constants import PROCESSING_FRAME_DURATION_SECONDS
from app.core.config.models import TranscriptionAggregationSettings
from app.transcription.contracts import TranscriptionSegmentAggregatorStats


class TranscriptionSegmentAggregatorImpl:
    """Aggregate completed speech segments before transcription execution."""

    def __init__(
        self,
        settings: TranscriptionAggregationSettings,
    ) -> None:
        self._settings = settings
        self._pending: SpeechSegment | None = None

        self._segments_received = 0
        self._segments_emitted = 0
        self._segments_combined = 0

        self._output_seconds_total = 0.0
        self._output_seconds_max = 0.0

    @property
    def stats(self) -> TranscriptionSegmentAggregatorStats:
        return TranscriptionSegmentAggregatorStats(
            segments_received=self._segments_received,
            segments_emitted=self._segments_emitted,
            segments_combined=self._segments_combined,
            output_seconds_total=self._output_seconds_total,
            output_seconds_max=self._output_seconds_max,
        )

    def process(
        self,
        segment: SpeechSegment,
    ) -> tuple[SpeechSegment, ...]:
        self._segments_received += 1

        if not self._settings.enabled:
            return self._emit(segment)

        pending = self._pending

        if pending is None:
            return self._handle_new_pending_candidate(segment)

        gap_seconds = self._gap_seconds(
            pending,
            segment,
        )

        trim_samples = 0

        if gap_seconds < 0.0:
            overlap_seconds = -gap_seconds

            if overlap_seconds > PROCESSING_FRAME_DURATION_SECONDS and not math.isclose(
                overlap_seconds,
                PROCESSING_FRAME_DURATION_SECONDS,
                rel_tol=0.0,
                abs_tol=1e-9,
            ):
                emitted = self._emit_pending()

                return (
                    *emitted,
                    *self._handle_new_pending_candidate(segment),
                )

            trim_samples = self._overlap_samples(
                overlap_seconds=overlap_seconds,
                sample_rate=segment.format.sample_rate,
            )

            if trim_samples >= segment.audio.shape[0]:
                emitted = self._emit_pending()

                return (
                    *emitted,
                    *self._handle_new_pending_candidate(segment),
                )

        if gap_seconds > self._settings.max_gap_seconds:
            emitted = self._emit_pending()

            return (
                *emitted,
                *self._handle_new_pending_candidate(segment),
            )

        gap_samples = 0

        if gap_seconds > 0.0:
            gap_samples = self._gap_samples(
                gap_seconds=gap_seconds,
                sample_rate=pending.format.sample_rate,
            )

        combined_sample_count = (
            pending.audio.shape[0] + gap_samples + segment.audio.shape[0] - trim_samples
        )

        combined_duration = combined_sample_count / pending.format.sample_rate

        if combined_duration > self._settings.max_duration_seconds:
            emitted = self._emit_pending()

            return (
                *emitted,
                *self._handle_new_pending_candidate(segment),
            )

        combined = self._combine(
            pending,
            segment,
            gap_samples=gap_samples,
            trim_samples=trim_samples,
        )

        self._segments_combined += 1
        self._pending = None

        return self._handle_new_pending_candidate(combined)

    def advance(
        self,
        timestamp: float,
    ) -> tuple[SpeechSegment, ...]:
        pending = self._pending

        if pending is None:
            return ()

        pending_end = pending.timestamp + pending.duration
        deadline = pending_end + self._settings.max_wait_seconds

        if timestamp < deadline:
            return ()

        return self._emit_pending()

    def flush(self) -> tuple[SpeechSegment, ...]:
        return self._emit_pending()

    def _emit_pending(self) -> tuple[SpeechSegment, ...]:
        pending = self._pending

        if pending is None:
            return ()

        self._pending = None
        return self._emit(pending)

    def _emit(
        self,
        segment: SpeechSegment,
    ) -> tuple[SpeechSegment, ...]:
        self._segments_emitted += 1
        self._output_seconds_total += segment.duration
        self._output_seconds_max = max(
            self._output_seconds_max,
            segment.duration,
        )

        return (segment,)

    def _handle_new_pending_candidate(
        self,
        segment: SpeechSegment,
    ) -> tuple[SpeechSegment, ...]:
        if (
            segment.duration >= self._settings.target_duration_seconds
            or self._settings.max_wait_seconds == 0.0
        ):
            return self._emit(segment)

        self._pending = segment
        return ()

    @staticmethod
    def _gap_seconds(
        first: SpeechSegment,
        second: SpeechSegment,
    ) -> float:
        first_end = first.timestamp + first.duration
        return second.timestamp - first_end

    @staticmethod
    def _gap_samples(
        *,
        gap_seconds: float,
        sample_rate: int,
    ) -> int:
        return round(gap_seconds * sample_rate)

    @staticmethod
    def _overlap_samples(
        *,
        overlap_seconds: float,
        sample_rate: int,
    ) -> int:
        return round(overlap_seconds * sample_rate)

    @staticmethod
    def _combine(
        first: SpeechSegment,
        second: SpeechSegment,
        *,
        gap_samples: int,
        trim_samples: int,
    ) -> SpeechSegment:
        silence = np.zeros(
            (
                gap_samples,
                first.format.channels,
            ),
            dtype=first.audio.dtype,
        )

        second_audio = second.audio[trim_samples:]

        audio = np.concatenate(
            (
                first.audio,
                silence,
                second_audio,
            ),
            axis=0,
        )

        duration = audio.shape[0] / first.format.sample_rate

        return SpeechSegment(
            audio=audio,
            timestamp=first.timestamp,
            duration=duration,
            format=first.format,
        )
