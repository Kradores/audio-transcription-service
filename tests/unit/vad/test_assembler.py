import numpy as np

from app.audio.contracts import (
    AudioFormat,
    ProcessingAudioFrame,
    SpeechEnd,
    SpeechSegment,
    SpeechStart,
)
from app.core.config.constants import PROCESSING_FRAME_DURATION_SECONDS
from app.core.config.models import AudioSegmentationSettings
from app.vad.assembler import SpeechSegmentAssemblerImpl

SAMPLE_RATE = 16_000
CHANNELS = 1
FRAME_SAMPLES = 320

PROCESSING_FORMAT = AudioFormat(
    sample_rate=SAMPLE_RATE,
    channels=CHANNELS,
    sample_type="float32",
)


def create_frame(
    index: int,
    *,
    value: float | None = None,
) -> ProcessingAudioFrame:
    frame_value = float(index) if value is None else value

    audio = np.full(
        (FRAME_SAMPLES, CHANNELS),
        frame_value,
        dtype=np.float32,
    )

    return ProcessingAudioFrame(
        audio=audio,
        timestamp=index * 0.020,
        format=PROCESSING_FORMAT,
    )


def create_settings(
    *,
    pre_roll_ms: int = 200,
    post_roll_ms: int = 200,
    target_duration_seconds: int = 3,
    max_duration_seconds: int = 5,
) -> AudioSegmentationSettings:
    return AudioSegmentationSettings(
        pre_roll_ms=pre_roll_ms,
        post_roll_ms=post_roll_ms,
        target_duration_seconds=target_duration_seconds,
        max_duration_seconds=max_duration_seconds,
    )


def test_speech_start_includes_available_pre_roll() -> None:
    # Arrange
    assembler = SpeechSegmentAssemblerImpl(
        settings=create_settings(pre_roll_ms=200),
    )

    frames = [create_frame(index) for index in range(5)]

    # Act
    for frame in frames[:-1]:
        result = assembler.process(frame, ())

        assert result == ()

    result = assembler.process(
        frames[-1],
        (SpeechStart(timestamp=frames[-1].timestamp),),
    )

    # Assert
    assert result == ()


def test_speech_start_preserves_available_pre_roll_until_segment_is_emitted() -> None:
    # Arrange
    assembler = SpeechSegmentAssemblerImpl(
        settings=create_settings(
            pre_roll_ms=200,
            post_roll_ms=0,
        ),
    )

    frames = [create_frame(index) for index in range(5)]

    # Act
    for frame in frames[:-1]:
        assert assembler.process(frame, ()) == ()

    assert (
        assembler.process(
            frames[-1],
            (SpeechStart(timestamp=frames[-1].timestamp),),
        )
        == ()
    )


def test_speech_start_preserves_available_pre_roll() -> None:
    # Arrange
    assembler = SpeechSegmentAssemblerImpl(
        settings=create_settings(
            pre_roll_ms=200,
            post_roll_ms=0,
        ),
    )

    frames = [create_frame(index) for index in range(6)]

    # Act
    for frame in frames[:5]:
        assert assembler.process(frame, ()) == ()

    assert (
        assembler.process(
            frames[5],
            (SpeechStart(timestamp=frames[5].timestamp),),
        )
        == ()
    )

    result = assembler.process(
        create_frame(6),
        (SpeechEnd(timestamp=0.120),),
    )

    # Assert
    assert len(result) == 1

    segment = result[0]

    assert segment.timestamp == frames[0].timestamp
    assert segment.duration == 0.140
    np.testing.assert_array_equal(
        segment.audio,
        np.concatenate([frame.audio for frame in frames + [create_frame(6)]]),
    )


def test_speech_start_includes_bounded_pre_roll_and_transition_frames() -> None:
    # Arrange
    assembler = SpeechSegmentAssemblerImpl(
        settings=create_settings(
            pre_roll_ms=200,
            post_roll_ms=0,
        ),
    )

    idle_frames = [create_frame(index) for index in range(12)]
    speech_start_frame = create_frame(12)
    speech_end_frame = create_frame(13)

    # Act
    for frame in idle_frames:
        result = assembler.process(frame, ())
        assert result == ()

    result = assembler.process(
        speech_start_frame,
        (SpeechStart(timestamp=speech_start_frame.timestamp),),
    )

    # SpeechStart alone does not complete a segment.
    assert result == ()

    result = assembler.process(
        speech_end_frame,
        (SpeechEnd(timestamp=speech_end_frame.timestamp),),
    )

    # Assert
    assert len(result) == 1

    segment = result[0]

    # 200 ms pre-roll = 10 frames.
    # Frames 0 and 1 must therefore have fallen out of the rolling buffer.
    expected_frames = [
        *idle_frames[2:],
        speech_start_frame,
        speech_end_frame,
    ]

    expected_audio = np.concatenate(
        [frame.audio for frame in expected_frames],
        axis=0,
    )

    assert segment.timestamp == idle_frames[2].timestamp
    assert segment.duration == len(expected_frames) * PROCESSING_FRAME_DURATION_SECONDS

    np.testing.assert_array_equal(
        segment.audio,
        expected_audio,
    )


def test_speaking_accumulates_frames_until_speech_end() -> None:
    # Arrange
    assembler = SpeechSegmentAssemblerImpl(
        settings=create_settings(
            pre_roll_ms=0,
            post_roll_ms=0,
        ),
    )

    speech_start_frame = create_frame(0)
    speech_frame_1 = create_frame(1)
    speech_frame_2 = create_frame(2)
    speech_end_frame = create_frame(3)

    # Act
    assert (
        assembler.process(
            speech_start_frame,
            (SpeechStart(timestamp=speech_start_frame.timestamp),),
        )
        == ()
    )

    assert assembler.process(speech_frame_1, ()) == ()
    assert assembler.process(speech_frame_2, ()) == ()

    result = assembler.process(
        speech_end_frame,
        (SpeechEnd(timestamp=speech_end_frame.timestamp),),
    )

    # Assert
    assert len(result) == 1

    segment = result[0]

    expected_frames = [
        speech_start_frame,
        speech_frame_1,
        speech_frame_2,
        speech_end_frame,
    ]

    expected_audio = np.concatenate(
        [frame.audio for frame in expected_frames],
        axis=0,
    )

    assert segment.timestamp == speech_start_frame.timestamp
    assert segment.duration == (len(expected_frames) * PROCESSING_FRAME_DURATION_SECONDS)

    np.testing.assert_array_equal(
        segment.audio,
        expected_audio,
    )


def test_speech_end_collects_configured_post_roll_before_emitting() -> None:
    # Arrange
    assembler = SpeechSegmentAssemblerImpl(
        settings=create_settings(
            pre_roll_ms=0,
            post_roll_ms=200,
        ),
    )

    speech_start_frame = create_frame(0)
    speech_end_frame = create_frame(1)
    post_roll_frames = [create_frame(index) for index in range(2, 12)]

    # Act
    assert (
        assembler.process(
            speech_start_frame,
            (SpeechStart(timestamp=speech_start_frame.timestamp),),
        )
        == ()
    )

    result = assembler.process(
        speech_end_frame,
        (SpeechEnd(timestamp=speech_end_frame.timestamp),),
    )

    # SpeechEnd starts post-roll; it must not emit yet.
    assert result == ()

    for frame in post_roll_frames[:-1]:
        result = assembler.process(frame, ())
        assert result == ()

    result = assembler.process(post_roll_frames[-1], ())

    # Assert
    assert len(result) == 1

    segment = result[0]

    expected_frames = [
        speech_start_frame,
        speech_end_frame,
        *post_roll_frames,
    ]

    expected_audio = np.concatenate(
        [frame.audio for frame in expected_frames],
        axis=0,
    )

    assert segment.timestamp == speech_start_frame.timestamp
    assert segment.duration == (len(expected_frames) * PROCESSING_FRAME_DURATION_SECONDS)

    np.testing.assert_array_equal(
        segment.audio,
        expected_audio,
    )


def test_post_roll_ignores_additional_vad_events() -> None:
    # Arrange
    assembler = SpeechSegmentAssemblerImpl(
        settings=create_settings(
            pre_roll_ms=0,
            post_roll_ms=100,
        ),
    )

    speech_start_frame = create_frame(0)
    speech_end_frame = create_frame(1)
    post_roll_frames = [create_frame(index) for index in range(2, 7)]

    # Act
    assert (
        assembler.process(
            speech_start_frame,
            (SpeechStart(timestamp=speech_start_frame.timestamp),),
        )
        == ()
    )

    assert (
        assembler.process(
            speech_end_frame,
            (SpeechEnd(timestamp=speech_end_frame.timestamp),),
        )
        == ()
    )

    # 100 ms = 5 frames.
    for index, frame in enumerate(post_roll_frames):
        if index < 4:
            result = assembler.process(
                frame,
                (SpeechStart(timestamp=frame.timestamp),),
            )
            assert result == ()
        else:
            result = assembler.process(
                frame,
                (SpeechStart(timestamp=frame.timestamp),),
            )

    # Assert
    assert len(result) == 1

    segment = result[0]

    expected_frames = [
        speech_start_frame,
        speech_end_frame,
        *post_roll_frames,
    ]

    expected_audio = np.concatenate(
        [frame.audio for frame in expected_frames],
        axis=0,
    )

    assert segment.timestamp == speech_start_frame.timestamp
    assert segment.duration == (len(expected_frames) * PROCESSING_FRAME_DURATION_SECONDS)

    np.testing.assert_array_equal(
        segment.audio,
        expected_audio,
    )


def test_max_duration_hard_splits_continuous_speech_without_overlap() -> None:
    # Arrange
    assembler = SpeechSegmentAssemblerImpl(
        settings=create_settings(
            pre_roll_ms=0,
            post_roll_ms=0,
            target_duration_seconds=1,
            max_duration_seconds=1,
        ),
    )

    frames = [create_frame(index) for index in range(100)]

    # Act
    results: list[SpeechSegment] = []

    results.extend(
        assembler.process(
            frames[0],
            (SpeechStart(timestamp=frames[0].timestamp),),
        ),
    )

    for frame in frames[1:]:
        results.extend(assembler.process(frame, ()))

    # Assert
    assert len(results) == 2

    first_segment = results[0]
    second_segment = results[1]

    assert first_segment.duration == 1.0
    assert second_segment.duration == 1.0

    np.testing.assert_array_equal(
        first_segment.audio,
        np.concatenate([frame.audio for frame in frames[:50]], axis=0),
    )

    np.testing.assert_array_equal(
        second_segment.audio,
        np.concatenate(
            [frame.audio for frame in frames[50:]],
            axis=0,
        ),
    )


def test_speech_end_on_max_duration_frame_emits_without_post_roll() -> None:
    # Arrange
    assembler = SpeechSegmentAssemblerImpl(
        settings=create_settings(
            pre_roll_ms=0,
            post_roll_ms=200,
            target_duration_seconds=1,
            max_duration_seconds=1,
        ),
    )

    frames = [create_frame(index) for index in range(50)]

    # Act
    results: list[SpeechSegment] = []

    results.extend(
        assembler.process(
            frames[0],
            (SpeechStart(timestamp=frames[0].timestamp),),
        ),
    )

    for frame in frames[1:-1]:
        results.extend(assembler.process(frame, ()))

    results.extend(
        assembler.process(
            frames[-1],
            (SpeechEnd(timestamp=frames[-1].timestamp),),
        ),
    )

    # Assert
    assert len(results) == 1

    segment = results[0]

    assert segment.timestamp == frames[0].timestamp
    assert segment.duration == 1.0

    np.testing.assert_array_equal(
        segment.audio,
        np.concatenate([frame.audio for frame in frames], axis=0),
    )


def test_reset_discards_in_progress_segment_and_returns_to_idle() -> None:
    # Arrange
    assembler = SpeechSegmentAssemblerImpl(
        settings=create_settings(
            pre_roll_ms=0,
            post_roll_ms=0,
        ),
    )

    speech_start_frame = create_frame(0)
    speech_frame = create_frame(1)

    # Act
    assert (
        assembler.process(
            speech_start_frame,
            (SpeechStart(timestamp=speech_start_frame.timestamp),),
        )
        == ()
    )

    assert assembler.process(speech_frame, ()) == ()

    assembler.reset()

    # New speech after reset must behave like a fresh assembler.
    new_speech_start_frame = create_frame(2)
    new_speech_end_frame = create_frame(3)

    assert (
        assembler.process(
            new_speech_start_frame,
            (SpeechStart(timestamp=new_speech_start_frame.timestamp),),
        )
        == ()
    )

    result = assembler.process(
        new_speech_end_frame,
        (SpeechEnd(timestamp=new_speech_end_frame.timestamp),),
    )

    # Assert
    assert len(result) == 1

    segment = result[0]

    expected_audio = np.concatenate(
        [
            new_speech_start_frame.audio,
            new_speech_end_frame.audio,
        ],
        axis=0,
    )

    assert segment.timestamp == new_speech_start_frame.timestamp
    assert segment.duration == 2 * PROCESSING_FRAME_DURATION_SECONDS

    np.testing.assert_array_equal(
        segment.audio,
        expected_audio,
    )


def test_reset_discards_post_roll_and_returns_to_idle() -> None:
    # Arrange
    assembler = SpeechSegmentAssemblerImpl(
        settings=create_settings(
            pre_roll_ms=0,
            post_roll_ms=100,
        ),
    )

    speech_start_frame = create_frame(0)
    speech_end_frame = create_frame(1)

    # Act
    assert (
        assembler.process(
            speech_start_frame,
            (SpeechStart(timestamp=speech_start_frame.timestamp),),
        )
        == ()
    )

    assert (
        assembler.process(
            speech_end_frame,
            (SpeechEnd(timestamp=speech_end_frame.timestamp),),
        )
        == ()
    )

    # Collect part of the old segment's post-roll.
    assert assembler.process(create_frame(2), ()) == ()
    assert assembler.process(create_frame(3), ()) == ()

    assembler.reset()

    # Start a completely new segment.
    new_speech_start_frame = create_frame(10)
    new_speech_end_frame = create_frame(11)

    assert (
        assembler.process(
            new_speech_start_frame,
            (SpeechStart(timestamp=new_speech_start_frame.timestamp),),
        )
        == ()
    )

    assert (
        assembler.process(
            new_speech_end_frame,
            (SpeechEnd(timestamp=new_speech_end_frame.timestamp),),
        )
        == ()
    )

    # 100 ms = 5 frames of post-roll.
    new_post_roll_frames = [create_frame(index) for index in range(12, 17)]

    results: list[SpeechSegment] = []

    for frame in new_post_roll_frames:
        results.extend(assembler.process(frame, ()))

    # Assert
    assert len(results) == 1

    segment = results[0]

    expected_frames = [
        new_speech_start_frame,
        new_speech_end_frame,
        *new_post_roll_frames,
    ]

    np.testing.assert_array_equal(
        segment.audio,
        np.concatenate(
            [frame.audio for frame in expected_frames],
            axis=0,
        ),
    )

    assert segment.timestamp == new_speech_start_frame.timestamp


def test_flush_discards_in_progress_segment_and_returns_no_segments() -> None:
    # Arrange
    assembler = SpeechSegmentAssemblerImpl(
        settings=create_settings(
            pre_roll_ms=0,
            post_roll_ms=0,
        ),
    )

    speech_start_frame = create_frame(0)
    speech_frame = create_frame(1)

    # Act
    assert (
        assembler.process(
            speech_start_frame,
            (SpeechStart(timestamp=speech_start_frame.timestamp),),
        )
        == ()
    )

    assert assembler.process(speech_frame, ()) == ()

    result = assembler.flush()

    # Assert
    assert result == ()

    # flush() must leave the assembler in IDLE.
    new_speech_start_frame = create_frame(2)
    new_speech_end_frame = create_frame(3)

    assert (
        assembler.process(
            new_speech_start_frame,
            (SpeechStart(timestamp=new_speech_start_frame.timestamp),),
        )
        == ()
    )

    result = assembler.process(
        new_speech_end_frame,
        (SpeechEnd(timestamp=new_speech_end_frame.timestamp),),
    )

    assert len(result) == 1

    segment = result[0]

    np.testing.assert_array_equal(
        segment.audio,
        np.concatenate(
            [
                new_speech_start_frame.audio,
                new_speech_end_frame.audio,
            ],
            axis=0,
        ),
    )


def test_flush_discards_post_roll_and_returns_no_segments() -> None:
    # Arrange
    assembler = SpeechSegmentAssemblerImpl(
        settings=create_settings(
            pre_roll_ms=0,
            post_roll_ms=100,
        ),
    )

    speech_start_frame = create_frame(0)
    speech_end_frame = create_frame(1)

    # Act
    assert (
        assembler.process(
            speech_start_frame,
            (SpeechStart(timestamp=speech_start_frame.timestamp),),
        )
        == ()
    )

    assert (
        assembler.process(
            speech_end_frame,
            (SpeechEnd(timestamp=speech_end_frame.timestamp),),
        )
        == ()
    )

    # 100 ms post-roll requires 5 frames.
    # Collect only part of it.
    assert assembler.process(create_frame(2), ()) == ()
    assert assembler.process(create_frame(3), ()) == ()

    result = assembler.flush()

    # Assert
    assert result == ()

    # flush() must return the assembler to IDLE.
    new_speech_start_frame = create_frame(10)
    new_speech_end_frame = create_frame(11)

    assert (
        assembler.process(
            new_speech_start_frame,
            (SpeechStart(timestamp=new_speech_start_frame.timestamp),),
        )
        == ()
    )

    assert (
        assembler.process(
            new_speech_end_frame,
            (SpeechEnd(timestamp=new_speech_end_frame.timestamp),),
        )
        == ()
    )

    new_post_roll_frames = [create_frame(index) for index in range(12, 17)]

    results: list[SpeechSegment] = []

    for frame in new_post_roll_frames:
        results.extend(assembler.process(frame, ()))

    assert len(results) == 1

    segment = results[0]

    expected_frames = [
        new_speech_start_frame,
        new_speech_end_frame,
        *new_post_roll_frames,
    ]

    np.testing.assert_array_equal(
        segment.audio,
        np.concatenate(
            [frame.audio for frame in expected_frames],
            axis=0,
        ),
    )


def test_post_roll_is_capped_by_max_duration() -> None:
    # Arrange
    assembler = SpeechSegmentAssemblerImpl(
        settings=create_settings(
            pre_roll_ms=0,
            post_roll_ms=200,
            target_duration_seconds=1,
            max_duration_seconds=1,
        ),
    )

    # 45 speech frames = 900 ms.
    speech_frames = [create_frame(index) for index in range(45)]

    # Act
    results: list[SpeechSegment] = []

    results.extend(
        assembler.process(
            speech_frames[0],
            (SpeechStart(timestamp=speech_frames[0].timestamp),),
        ),
    )

    for frame in speech_frames[1:-1]:
        results.extend(assembler.process(frame, ()))

    # SpeechEnd occurs at 900 ms.
    results.extend(
        assembler.process(
            speech_frames[-1],
            (SpeechEnd(timestamp=speech_frames[-1].timestamp),),
        ),
    )

    # We need 5 post-roll frames to reach the 1 second maximum.
    post_roll_frames = [create_frame(index) for index in range(45, 50)]

    for frame in post_roll_frames[:-1]:
        results.extend(assembler.process(frame, ()))

    results.extend(assembler.process(post_roll_frames[-1], ()))

    # Assert
    assert len(results) == 1

    segment = results[0]

    expected_frames = [
        *speech_frames,
        *post_roll_frames,
    ]

    assert segment.duration == 1.0

    np.testing.assert_array_equal(
        segment.audio,
        np.concatenate(
            [frame.audio for frame in expected_frames],
            axis=0,
        ),
    )


def test_pre_roll_is_bounded_by_max_duration() -> None:
    # Arrange
    assembler = SpeechSegmentAssemblerImpl(
        settings=create_settings(
            pre_roll_ms=980,
            post_roll_ms=0,
            target_duration_seconds=1,
            max_duration_seconds=1,
        ),
    )

    idle_frames = [create_frame(index) for index in range(49)]
    speech_start_frame = create_frame(49)

    # Act
    results: list[SpeechSegment] = []

    for frame in idle_frames:
        assert assembler.process(frame, ()) == ()

    results.extend(
        assembler.process(
            speech_start_frame,
            (SpeechStart(timestamp=speech_start_frame.timestamp),),
        ),
    )

    # Assert
    assert len(results) == 1

    segment = results[0]

    expected_frames = [
        *idle_frames,
        speech_start_frame,
    ]

    assert segment.duration == 1.0

    np.testing.assert_array_equal(
        segment.audio,
        np.concatenate(
            [frame.audio for frame in expected_frames],
            axis=0,
        ),
    )
