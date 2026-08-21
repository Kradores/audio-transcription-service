from app.audio.timeline import MonotonicAudioTimeline


class FakeClock:
    def __init__(self, value: float) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value


def test_monotonic_audio_timeline_is_relative_to_creation() -> None:
    clock = FakeClock(100.0)
    timeline = MonotonicAudioTimeline(clock)

    clock.value = 103.25

    assert timeline.now() == 3.25


def test_monotonic_audio_timeline_starts_at_zero() -> None:
    clock = FakeClock(100.0)

    timeline = MonotonicAudioTimeline(clock)

    assert timeline.now() == 0.0
