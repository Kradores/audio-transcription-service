from dataclasses import FrozenInstanceError

import numpy as np
import pytest

from app.audio.contracts import AudioFormat, SpeechSegment
from app.core.config.models import TranscriptionAggregationSettings
from app.transcription.aggregation import TranscriptionSegmentAggregatorImpl

SAMPLE_RATE = 16_000

AUDIO_FORMAT = AudioFormat(
    sample_rate=SAMPLE_RATE,
    channels=1,
    sample_type="float32",
)


def create_settings(
    *,
    enabled: bool = True,
    target_duration_seconds: float = 5.0,
    max_duration_seconds: float = 10.0,
    max_gap_seconds: float = 1.5,
    max_wait_seconds: float = 2.0,
) -> TranscriptionAggregationSettings:
    return TranscriptionAggregationSettings(
        enabled=enabled,
        target_duration_seconds=target_duration_seconds,
        max_duration_seconds=max_duration_seconds,
        max_gap_seconds=max_gap_seconds,
        max_wait_seconds=max_wait_seconds,
    )


def create_segment(
    *,
    timestamp: float = 10.0,
    duration: float = 1.0,
    value: float = 1.0,
) -> SpeechSegment:
    sample_count = round(duration * SAMPLE_RATE)

    audio = np.full(
        (sample_count, 1),
        value,
        dtype=np.float32,
    )

    return SpeechSegment(
        audio=audio,
        timestamp=timestamp,
        duration=sample_count / SAMPLE_RATE,
        format=AUDIO_FORMAT,
    )


def test_short_segment_is_buffered() -> None:
    # Arrange
    aggregator = TranscriptionSegmentAggregatorImpl(
        create_settings(),
    )
    segment = create_segment(duration=1.0)

    # Act
    result = aggregator.process(segment)

    # Assert
    assert result == ()
    assert aggregator.stats.segments_received == 1
    assert aggregator.stats.segments_emitted == 0


def test_segment_at_target_duration_is_emitted_immediately() -> None:
    # Arrange
    aggregator = TranscriptionSegmentAggregatorImpl(
        create_settings(
            target_duration_seconds=5.0,
        ),
    )
    segment = create_segment(duration=5.0)

    # Act
    result = aggregator.process(segment)

    # Assert
    assert result == (segment,)


def test_segment_above_target_duration_is_emitted_immediately() -> None:
    # Arrange
    aggregator = TranscriptionSegmentAggregatorImpl(
        create_settings(
            target_duration_seconds=5.0,
        ),
    )
    segment = create_segment(duration=7.0)

    # Act
    result = aggregator.process(segment)

    # Assert
    assert result == (segment,)


def test_flush_emits_pending_segment() -> None:
    # Arrange
    aggregator = TranscriptionSegmentAggregatorImpl(
        create_settings(),
    )
    segment = create_segment(duration=1.0)

    assert aggregator.process(segment) == ()

    # Act
    result = aggregator.flush()

    # Assert
    assert result == (segment,)


def test_flush_clears_pending_segment() -> None:
    # Arrange
    aggregator = TranscriptionSegmentAggregatorImpl(
        create_settings(),
    )
    segment = create_segment(duration=1.0)

    assert aggregator.process(segment) == ()

    # Act
    first = aggregator.flush()
    second = aggregator.flush()

    # Assert
    assert first == (segment,)
    assert second == ()


def test_advance_does_not_emit_before_max_wait_expires() -> None:
    # Arrange
    aggregator = TranscriptionSegmentAggregatorImpl(
        create_settings(
            max_wait_seconds=2.0,
        ),
    )
    segment = create_segment(
        timestamp=10.0,
        duration=1.0,
    )

    assert aggregator.process(segment) == ()

    # Act
    result = aggregator.advance(12.999)

    # Assert
    assert result == ()


def test_advance_emits_when_max_wait_expires() -> None:
    # Arrange
    aggregator = TranscriptionSegmentAggregatorImpl(
        create_settings(
            max_wait_seconds=2.0,
        ),
    )
    segment = create_segment(
        timestamp=10.0,
        duration=1.0,
    )

    assert aggregator.process(segment) == ()

    # Act
    result = aggregator.advance(13.0)

    # Assert
    assert result == (segment,)


def test_advance_clears_expired_pending_segment() -> None:
    # Arrange
    aggregator = TranscriptionSegmentAggregatorImpl(
        create_settings(
            max_wait_seconds=2.0,
        ),
    )
    segment = create_segment(
        timestamp=10.0,
        duration=1.0,
    )

    assert aggregator.process(segment) == ()

    # Act
    first = aggregator.advance(13.0)
    second = aggregator.advance(14.0)

    # Assert
    assert first == (segment,)
    assert second == ()


def test_disabled_aggregation_emits_segment_immediately() -> None:
    # Arrange
    aggregator = TranscriptionSegmentAggregatorImpl(
        create_settings(
            enabled=False,
        ),
    )
    segment = create_segment(duration=1.0)

    # Act
    result = aggregator.process(segment)

    # Assert
    assert result == (segment,)


def test_zero_max_wait_emits_short_segment_immediately() -> None:
    # Arrange
    aggregator = TranscriptionSegmentAggregatorImpl(
        create_settings(
            max_wait_seconds=0.0,
        ),
    )
    segment = create_segment(duration=1.0)

    # Act
    result = aggregator.process(segment)

    # Assert
    assert result == (segment,)


def test_second_segment_does_not_replace_pending_segment() -> None:
    # Arrange
    aggregator = TranscriptionSegmentAggregatorImpl(
        create_settings(),
    )
    first = create_segment(
        timestamp=10.0,
        duration=1.0,
        value=1.0,
    )
    second = create_segment(
        timestamp=12.0,
        duration=1.0,
        value=2.0,
    )

    assert aggregator.process(first) == ()

    # Act
    result = aggregator.process(second)

    # Assert
    assert result == (first,)
    assert aggregator.flush() == (second,)


def test_stats_describe_received_and_emitted_segments() -> None:
    # Arrange
    aggregator = TranscriptionSegmentAggregatorImpl(
        create_settings(),
    )
    short_segment = create_segment(
        timestamp=10.0,
        duration=1.0,
    )
    long_segment = create_segment(
        timestamp=20.0,
        duration=5.0,
    )

    # Act
    assert aggregator.process(short_segment) == ()
    assert aggregator.flush() == (short_segment,)
    assert aggregator.process(long_segment) == (long_segment,)

    stats = aggregator.stats

    # Assert
    assert stats.segments_received == 2
    assert stats.segments_emitted == 2
    assert stats.segments_combined == 0

    assert stats.output_seconds_total == 6.0
    assert stats.output_seconds_average == 3.0
    assert stats.output_seconds_max == 5.0


def test_stats_snapshot_is_immutable() -> None:
    # Arrange
    aggregator = TranscriptionSegmentAggregatorImpl(
        create_settings(),
    )
    stats = aggregator.stats

    # Act / Assert
    with pytest.raises(FrozenInstanceError):
        stats.segments_received = 1  # type: ignore[misc]


def test_stats_are_returned_as_snapshots() -> None:
    # Arrange
    aggregator = TranscriptionSegmentAggregatorImpl(
        create_settings(),
    )

    before = aggregator.stats

    # Act
    aggregator.process(
        create_segment(duration=5.0),
    )

    after = aggregator.stats

    # Assert
    assert before.segments_received == 0
    assert before.segments_emitted == 0

    assert after.segments_received == 1
    assert after.segments_emitted == 1
