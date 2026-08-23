from __future__ import annotations

from app.audio.contracts import SpeechSegment
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

        emitted: list[SpeechSegment] = []

        if self._pending is not None:
            emitted.extend(self._emit_pending())

        if (
            segment.duration >= self._settings.target_duration_seconds
            or self._settings.max_wait_seconds == 0.0
        ):
            emitted.extend(self._emit(segment))
        else:
            self._pending = segment

        return tuple(emitted)

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
