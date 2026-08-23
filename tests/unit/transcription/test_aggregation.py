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
        create_settings(
            max_gap_seconds=1.5,
        ),
    )
    first = create_segment(
        timestamp=10.0,
        duration=1.0,
        value=1.0,
    )
    second = create_segment(
        timestamp=12.6,
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


def test_contiguous_short_segments_are_combined() -> None:
    # Arrange
    aggregator = TranscriptionSegmentAggregatorImpl(
        create_settings(
            target_duration_seconds=5.0,
        ),
    )
    first = create_segment(
        timestamp=10.0,
        duration=1.0,
        value=1.0,
    )
    second = create_segment(
        timestamp=11.0,
        duration=1.5,
        value=2.0,
    )

    assert aggregator.process(first) == ()

    # Act
    result = aggregator.process(second)

    # Assert
    assert result == ()

    flushed = aggregator.flush()

    assert len(flushed) == 1

    combined = flushed[0]

    assert combined.timestamp == 10.0
    assert combined.duration == 2.5

    np.testing.assert_array_equal(
        combined.audio[:SAMPLE_RATE],
        first.audio,
    )
    np.testing.assert_array_equal(
        combined.audio[SAMPLE_RATE:],
        second.audio,
    )


def test_combined_segment_is_emitted_when_target_is_reached() -> None:
    # Arrange
    aggregator = TranscriptionSegmentAggregatorImpl(
        create_settings(
            target_duration_seconds=5.0,
        ),
    )
    first = create_segment(
        timestamp=10.0,
        duration=2.0,
        value=1.0,
    )
    second = create_segment(
        timestamp=12.0,
        duration=3.0,
        value=2.0,
    )

    assert aggregator.process(first) == ()

    # Act
    result = aggregator.process(second)

    # Assert
    assert len(result) == 1

    combined = result[0]

    assert combined.timestamp == 10.0
    assert combined.duration == 5.0
    assert aggregator.flush() == ()


def test_multiple_contiguous_segments_are_combined_until_target() -> None:
    # Arrange
    aggregator = TranscriptionSegmentAggregatorImpl(
        create_settings(
            target_duration_seconds=5.0,
        ),
    )
    first = create_segment(
        timestamp=10.0,
        duration=1.0,
        value=1.0,
    )
    second = create_segment(
        timestamp=11.0,
        duration=1.5,
        value=2.0,
    )
    third = create_segment(
        timestamp=12.5,
        duration=2.5,
        value=3.0,
    )

    # Act
    first_result = aggregator.process(first)
    second_result = aggregator.process(second)
    third_result = aggregator.process(third)

    # Assert
    assert first_result == ()
    assert second_result == ()
    assert len(third_result) == 1

    combined = third_result[0]

    assert combined.timestamp == 10.0
    assert combined.duration == 5.0

    expected = np.concatenate(
        (
            first.audio,
            second.audio,
            third.audio,
        ),
        axis=0,
    )

    np.testing.assert_array_equal(
        combined.audio,
        expected,
    )


def test_segment_is_not_combined_when_max_duration_would_be_exceeded() -> None:
    # Arrange
    aggregator = TranscriptionSegmentAggregatorImpl(
        create_settings(
            target_duration_seconds=8.0,
            max_duration_seconds=10.0,
        ),
    )
    first = create_segment(
        timestamp=10.0,
        duration=6.0,
        value=1.0,
    )
    second = create_segment(
        timestamp=16.0,
        duration=5.0,
        value=2.0,
    )

    assert aggregator.process(first) == ()

    # Act
    result = aggregator.process(second)

    # Assert
    assert result == (first,)

    assert aggregator.flush() == (second,)


def test_combination_may_reach_exact_max_duration() -> None:
    # Arrange
    aggregator = TranscriptionSegmentAggregatorImpl(
        create_settings(
            target_duration_seconds=10.0,
            max_duration_seconds=10.0,
        ),
    )
    first = create_segment(
        timestamp=10.0,
        duration=4.0,
    )
    second = create_segment(
        timestamp=14.0,
        duration=6.0,
    )

    assert aggregator.process(first) == ()

    # Act
    result = aggregator.process(second)

    # Assert
    assert len(result) == 1
    assert result[0].duration == 10.0


def test_positive_gap_is_filled_with_silence() -> None:
    # Arrange
    aggregator = TranscriptionSegmentAggregatorImpl(
        create_settings(
            target_duration_seconds=5.0,
            max_gap_seconds=1.5,
        ),
    )
    first = create_segment(
        timestamp=10.0,
        duration=1.0,
        value=1.0,
    )
    second = create_segment(
        timestamp=11.5,
        duration=1.0,
        value=2.0,
    )

    assert aggregator.process(first) == ()

    # Act
    result = aggregator.process(second)

    # Assert
    assert result == ()

    combined = aggregator.flush()[0]

    assert combined.timestamp == 10.0
    assert combined.duration == 2.5

    first_end = SAMPLE_RATE
    silence_end = first_end + (SAMPLE_RATE // 2)

    np.testing.assert_array_equal(
        combined.audio[:first_end],
        first.audio,
    )

    np.testing.assert_array_equal(
        combined.audio[first_end:silence_end],
        np.zeros(
            (SAMPLE_RATE // 2, 1),
            dtype=np.float32,
        ),
    )

    np.testing.assert_array_equal(
        combined.audio[silence_end:],
        second.audio,
    )


def test_small_overlap_is_trimmed_and_segments_are_combined() -> None:
    # Arrange
    aggregator = TranscriptionSegmentAggregatorImpl(
        create_settings(
            target_duration_seconds=5.0,
        ),
    )
    first = create_segment(
        timestamp=10.0,
        duration=1.0,
        value=1.0,
    )
    second = create_segment(
        timestamp=10.98,
        duration=1.0,
        value=2.0,
    )

    assert aggregator.process(first) == ()

    # Act
    result = aggregator.process(second)

    # Assert
    assert result == ()

    combined = aggregator.flush()[0]

    expected_overlap_samples = 320

    assert combined.timestamp == 10.0
    assert combined.audio.shape == (
        (2 * SAMPLE_RATE) - expected_overlap_samples,
        1,
    )
    assert combined.duration == pytest.approx(1.98)

    np.testing.assert_array_equal(
        combined.audio[:SAMPLE_RATE],
        first.audio,
    )

    np.testing.assert_array_equal(
        combined.audio[SAMPLE_RATE:],
        second.audio[expected_overlap_samples:],
    )


def test_stats_count_combined_input_segments() -> None:
    # Arrange
    aggregator = TranscriptionSegmentAggregatorImpl(
        create_settings(
            target_duration_seconds=5.0,
        ),
    )

    first = create_segment(
        timestamp=10.0,
        duration=1.0,
    )
    second = create_segment(
        timestamp=11.0,
        duration=1.5,
    )
    third = create_segment(
        timestamp=12.5,
        duration=2.5,
    )

    # Act
    aggregator.process(first)
    aggregator.process(second)
    aggregator.process(third)

    stats = aggregator.stats

    # Assert
    assert stats.segments_received == 3
    assert stats.segments_emitted == 1
    assert stats.segments_combined == 2

    assert stats.output_seconds_total == 5.0
    assert stats.output_seconds_average == 5.0
    assert stats.output_seconds_max == 5.0


def test_half_second_gap_inserts_exact_sample_count() -> None:
    # Arrange
    aggregator = TranscriptionSegmentAggregatorImpl(
        create_settings(),
    )
    first = create_segment(
        timestamp=10.0,
        duration=1.0,
    )
    second = create_segment(
        timestamp=11.5,
        duration=1.0,
    )

    assert aggregator.process(first) == ()

    # Act
    aggregator.process(second)
    combined = aggregator.flush()[0]

    # Assert
    expected_samples = SAMPLE_RATE + 8_000 + SAMPLE_RATE

    assert combined.audio.shape == (
        expected_samples,
        1,
    )


def test_gap_equal_to_max_gap_is_combined() -> None:
    # Arrange
    aggregator = TranscriptionSegmentAggregatorImpl(
        create_settings(
            target_duration_seconds=5.0,
            max_gap_seconds=1.5,
        ),
    )
    first = create_segment(
        timestamp=10.0,
        duration=1.0,
    )
    second = create_segment(
        timestamp=12.5,
        duration=1.0,
    )

    assert aggregator.process(first) == ()

    # Act
    result = aggregator.process(second)

    # Assert
    assert result == ()

    combined = aggregator.flush()[0]

    assert combined.timestamp == 10.0
    assert combined.duration == 3.5


def test_gap_above_max_gap_forms_boundary() -> None:
    # Arrange
    aggregator = TranscriptionSegmentAggregatorImpl(
        create_settings(
            max_gap_seconds=1.5,
        ),
    )
    first = create_segment(
        timestamp=10.0,
        duration=1.0,
    )
    second = create_segment(
        timestamp=12.51,
        duration=1.0,
    )

    assert aggregator.process(first) == ()

    # Act
    result = aggregator.process(second)

    # Assert
    assert result == (first,)
    assert aggregator.flush() == (second,)


def test_synthesized_gap_counts_toward_target_duration() -> None:
    # Arrange
    aggregator = TranscriptionSegmentAggregatorImpl(
        create_settings(
            target_duration_seconds=5.0,
            max_gap_seconds=1.5,
        ),
    )
    first = create_segment(
        timestamp=10.0,
        duration=2.0,
    )
    second = create_segment(
        timestamp=13.0,
        duration=2.0,
    )

    assert aggregator.process(first) == ()

    # Act
    result = aggregator.process(second)

    # Assert
    assert len(result) == 1

    combined = result[0]

    assert combined.timestamp == 10.0
    assert combined.duration == 5.0
    assert aggregator.flush() == ()


def test_synthesized_gap_counts_toward_max_duration() -> None:
    # Arrange
    aggregator = TranscriptionSegmentAggregatorImpl(
        create_settings(
            target_duration_seconds=9.0,
            max_duration_seconds=10.0,
            max_gap_seconds=1.5,
        ),
    )
    first = create_segment(
        timestamp=10.0,
        duration=5.0,
    )
    second = create_segment(
        timestamp=16.0,
        duration=5.0,
    )

    assert aggregator.process(first) == ()

    # Act
    result = aggregator.process(second)

    # Assert
    assert result == (first,)
    assert aggregator.flush() == (second,)


def test_stats_include_synthesized_silence_in_output_duration() -> None:
    # Arrange
    aggregator = TranscriptionSegmentAggregatorImpl(
        create_settings(
            target_duration_seconds=5.0,
        ),
    )
    first = create_segment(
        timestamp=10.0,
        duration=2.0,
    )
    second = create_segment(
        timestamp=13.0,
        duration=2.0,
    )

    # Act
    aggregator.process(first)
    aggregator.process(second)

    stats = aggregator.stats

    # Assert
    assert stats.segments_received == 2
    assert stats.segments_emitted == 1
    assert stats.segments_combined == 1

    assert stats.output_seconds_total == 5.0
    assert stats.output_seconds_average == 5.0
    assert stats.output_seconds_max == 5.0


def test_overlap_equal_to_processing_frame_duration_is_combined() -> None:
    # Arrange
    aggregator = TranscriptionSegmentAggregatorImpl(
        create_settings(),
    )
    first = create_segment(
        timestamp=10.0,
        duration=1.0,
    )
    second = create_segment(
        timestamp=10.98,
        duration=1.0,
    )

    assert aggregator.process(first) == ()

    # Act
    result = aggregator.process(second)

    # Assert
    assert result == ()

    combined = aggregator.flush()[0]

    assert combined.duration == pytest.approx(1.98)


def test_overlap_above_processing_frame_duration_forms_boundary() -> None:
    # Arrange
    aggregator = TranscriptionSegmentAggregatorImpl(
        create_settings(),
    )
    first = create_segment(
        timestamp=10.0,
        duration=1.0,
    )
    second = create_segment(
        timestamp=10.979,
        duration=1.0,
    )

    assert aggregator.process(first) == ()

    # Act
    result = aggregator.process(second)

    # Assert
    assert result == (first,)
    assert aggregator.flush() == (second,)


def test_trimmed_overlap_counts_toward_actual_target_duration() -> None:
    # Arrange
    aggregator = TranscriptionSegmentAggregatorImpl(
        create_settings(
            target_duration_seconds=2.0,
        ),
    )
    first = create_segment(
        timestamp=10.0,
        duration=1.0,
    )
    second = create_segment(
        timestamp=10.98,
        duration=1.0,
    )

    assert aggregator.process(first) == ()

    # Act
    result = aggregator.process(second)

    # Assert
    assert result == ()
    assert aggregator.flush()[0].duration == pytest.approx(1.98)


def test_trimmed_overlap_uses_actual_duration_for_maximum() -> None:
    # Arrange
    aggregator = TranscriptionSegmentAggregatorImpl(
        create_settings(
            target_duration_seconds=1.99,
            max_duration_seconds=1.99,
        ),
    )
    first = create_segment(
        timestamp=10.0,
        duration=1.0,
    )
    second = create_segment(
        timestamp=10.99,
        duration=1.0,
    )

    assert aggregator.process(first) == ()

    # Act
    result = aggregator.process(second)

    # Assert
    assert len(result) == 1
    assert result[0].duration == pytest.approx(1.99)