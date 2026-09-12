from __future__ import annotations

import logging

import numpy as np
import pytest

from app.audio.contracts import AudioFormat, SpeechSegment
from app.core.config.enums import TranscriptionLanguageMode
from app.core.config.models import AdaptiveTranscriptionLanguageSettings
from app.transcription.adaptive_language_state import AdaptiveLanguageStateStore
from app.transcription.adaptive_processor import AdaptiveTranscriptionProcessor
from app.transcription.contracts import (
    AudioSource,
    TranscriptionResult,
    TranscriptionWorkItem,
)


class FakeTranscriber:
    def __init__(
        self,
        *,
        auto_results: list[tuple[str, float]],
    ) -> None:
        self._auto_results = auto_results
        self.calls: list[tuple[SpeechSegment, str | None]] = []

    def transcribe(
        self,
        segment: SpeechSegment,
        *,
        language: str | None = None,
    ) -> TranscriptionResult:
        self.calls.append((segment, language))

        if language is None:
            detected_language, confidence = self._auto_results.pop(0)

            return TranscriptionResult(
                text="text",
                language=detected_language,
                confidence=confidence,
                start=segment.timestamp,
                end=segment.timestamp + segment.duration,
            )

        return TranscriptionResult(
            text="text",
            language=language,
            confidence=None,
            start=segment.timestamp,
            end=segment.timestamp + segment.duration,
        )


def create_settings(
    *,
    initial_language: str | None = None,
    candidate_max_gap_seconds: float = 30.0,
) -> AdaptiveTranscriptionLanguageSettings:
    return AdaptiveTranscriptionLanguageSettings(
        mode=TranscriptionLanguageMode.ADAPTIVE,
        initial_language=initial_language,
        min_probe_duration_seconds=3.0,
        switch_probability_threshold=0.85,
        switch_confirmations=2,
        candidate_max_gap_seconds=candidate_max_gap_seconds,
    )


def create_processor(
    *,
    transcriber: FakeTranscriber,
    settings: AdaptiveTranscriptionLanguageSettings,
    state_store: AdaptiveLanguageStateStore | None = None,
) -> AdaptiveTranscriptionProcessor:
    return AdaptiveTranscriptionProcessor(
        transcriber=transcriber,
        settings=settings,
        state_store=(
            state_store
            if state_store is not None
            else AdaptiveLanguageStateStore(
                initial_language=settings.initial_language,
            )
        ),
    )


def create_item(
    *,
    duration: float,
    timestamp: float = 0.0,
    source: AudioSource = AudioSource.MICROPHONE,
) -> TranscriptionWorkItem:
    sample_rate = 16_000
    sample_count = int(sample_rate * duration)

    segment = SpeechSegment(
        audio=np.zeros(
            (sample_count, 1),
            dtype=np.float32,
        ),
        timestamp=timestamp,
        duration=duration,
        format=AudioFormat(
            sample_rate=sample_rate,
            channels=1,
            sample_type="float32",
        ),
    )

    return TranscriptionWorkItem(
        source=source,
        segment=segment,
    )


def test_unknown_short_segment_uses_auto_and_does_not_establish_language() -> None:
    transcriber = FakeTranscriber(
        auto_results=[
            ("ru", 0.95),
            ("ro", 0.90),
        ],
    )
    settings = create_settings()
    processor = create_processor(
        transcriber=transcriber,
        settings=settings,
    )

    processor.process(
        create_item(
            duration=1.0,
            timestamp=0.0,
        )
    )
    processor.process(
        create_item(
            duration=1.0,
            timestamp=2.0,
        )
    )

    assert [language for _, language in transcriber.calls] == [
        None,
        None,
    ]


def test_unknown_probe_with_low_confidence_does_not_establish_language() -> None:
    transcriber = FakeTranscriber(
        auto_results=[
            ("ro", 0.60),
            ("ru", 0.40),
        ],
    )
    settings = create_settings()
    processor = create_processor(
        transcriber=transcriber,
        settings=settings,
    )

    processor.process(
        create_item(
            duration=4.0,
            timestamp=0.0,
        )
    )
    processor.process(
        create_item(
            duration=1.0,
            timestamp=5.0,
        )
    )

    assert [language for _, language in transcriber.calls] == [
        None,
        None,
    ]


def test_unknown_strong_probe_creates_candidate_without_establishing_language() -> None:
    transcriber = FakeTranscriber(
        auto_results=[
            ("ro", 0.96),
            ("en", 0.40),
        ],
    )
    settings = create_settings()
    processor = create_processor(
        transcriber=transcriber,
        settings=settings,
    )

    first_result = processor.process(
        create_item(
            duration=4.0,
            timestamp=0.0,
        )
    )

    second_result = processor.process(
        create_item(
            duration=1.0,
            timestamp=5.0,
        )
    )

    assert [language for _, language in transcriber.calls] == [
        None,
        None,
    ]

    assert first_result.result.language == "ro"
    assert first_result.result.confidence == 0.96

    assert second_result.result.language == "en"
    assert second_result.result.confidence == 0.40


def test_unknown_second_strong_probe_establishes_candidate_language() -> None:
    transcriber = FakeTranscriber(
        auto_results=[
            ("ro", 0.96),
            ("ro", 0.95),
        ],
    )
    settings = create_settings()
    processor = create_processor(
        transcriber=transcriber,
        settings=settings,
    )

    processor.process(
        create_item(
            duration=4.0,
            timestamp=0.0,
        )
    )

    processor.process(
        create_item(
            duration=4.0,
            timestamp=5.0,
        )
    )

    short_result = processor.process(
        create_item(
            duration=1.0,
            timestamp=10.0,
        )
    )

    assert [language for _, language in transcriber.calls] == [
        None,
        None,
        "ro",
    ]

    assert short_result.result.language == "ro"
    assert short_result.result.confidence is None


def test_unknown_competing_strong_probe_replaces_bootstrap_candidate() -> None:
    transcriber = FakeTranscriber(
        auto_results=[
            ("ru", 0.90),
            ("ro", 0.92),
            ("ro", 0.93),
        ],
    )
    settings = create_settings()
    processor = create_processor(
        transcriber=transcriber,
        settings=settings,
    )

    processor.process(
        create_item(
            duration=8.0,
            timestamp=0.0,
        )
    )

    processor.process(
        create_item(
            duration=6.0,
            timestamp=9.0,
        )
    )

    processor.process(
        create_item(
            duration=6.0,
            timestamp=16.0,
        )
    )

    short_result = processor.process(
        create_item(
            duration=1.0,
            timestamp=23.0,
        )
    )

    assert [language for _, language in transcriber.calls] == [
        None,
        None,
        None,
        "ro",
    ]

    assert short_result.result.language == "ro"
    assert short_result.result.confidence is None


def test_unknown_low_confidence_probe_preserves_bootstrap_candidate() -> None:
    transcriber = FakeTranscriber(
        auto_results=[
            ("ro", 0.96),
            ("en", 0.60),
            ("ro", 0.95),
        ],
    )
    settings = create_settings()
    processor = create_processor(
        transcriber=transcriber,
        settings=settings,
    )

    processor.process(
        create_item(
            duration=4.0,
            timestamp=0.0,
        )
    )

    processor.process(
        create_item(
            duration=4.0,
            timestamp=5.0,
        )
    )

    processor.process(
        create_item(
            duration=4.0,
            timestamp=10.0,
        )
    )

    short_result = processor.process(
        create_item(
            duration=1.0,
            timestamp=15.0,
        )
    )

    assert [language for _, language in transcriber.calls] == [
        None,
        None,
        None,
        "ro",
    ]

    assert short_result.result.language == "ro"
    assert short_result.result.confidence is None


def test_initial_language_is_used_for_first_short_segment() -> None:
    transcriber = FakeTranscriber(
        auto_results=[],
    )
    settings = create_settings(
        initial_language="ro",
    )
    processor = create_processor(
        transcriber=transcriber,
        settings=settings,
    )

    result = processor.process(
        create_item(
            duration=1.0,
        )
    )

    assert [language for _, language in transcriber.calls] == [
        "ro",
    ]

    assert result.result.language == "ro"
    assert result.result.confidence is None


def test_established_language_probe_uses_auto_detection() -> None:
    transcriber = FakeTranscriber(
        auto_results=[
            ("ro", 0.96),
        ],
    )
    settings = create_settings(
        initial_language="ro",
    )
    processor = create_processor(
        transcriber=transcriber,
        settings=settings,
    )

    result = processor.process(
        create_item(
            duration=4.0,
        )
    )

    assert [language for _, language in transcriber.calls] == [
        None,
    ]

    assert result.result.language == "ro"
    assert result.result.confidence == 0.96


def test_same_language_probe_keeps_language_established_for_next_short_segment() -> None:
    transcriber = FakeTranscriber(
        auto_results=[
            ("ro", 0.97),
        ],
    )
    settings = create_settings(
        initial_language="ro",
    )
    processor = create_processor(
        transcriber=transcriber,
        settings=settings,
    )

    processor.process(
        create_item(
            duration=4.0,
            timestamp=0.0,
        )
    )
    short_result = processor.process(
        create_item(
            duration=1.0,
            timestamp=5.0,
        )
    )

    assert [language for _, language in transcriber.calls] == [
        None,
        "ro",
    ]

    assert short_result.result.language == "ro"
    assert short_result.result.confidence is None


def test_strong_competing_probe_does_not_immediately_replace_established_language() -> None:
    transcriber = FakeTranscriber(
        auto_results=[
            ("en", 0.96),
        ],
    )
    settings = create_settings(
        initial_language="ro",
    )
    processor = create_processor(
        transcriber=transcriber,
        settings=settings,
    )

    probe_result = processor.process(
        create_item(
            duration=4.0,
            timestamp=0.0,
        )
    )
    short_result = processor.process(
        create_item(
            duration=1.0,
            timestamp=5.0,
        )
    )

    assert [language for _, language in transcriber.calls] == [
        None,
        "ro",
    ]

    assert probe_result.result.language == "en"
    assert probe_result.result.confidence == 0.96

    assert short_result.result.language == "ro"
    assert short_result.result.confidence is None


def test_second_strong_competing_probe_switches_established_language() -> None:
    transcriber = FakeTranscriber(
        auto_results=[
            ("en", 0.96),
            ("en", 0.94),
        ],
    )
    settings = create_settings(
        initial_language="ro",
    )
    processor = create_processor(
        transcriber=transcriber,
        settings=settings,
    )

    first_probe_result = processor.process(
        create_item(
            duration=4.0,
            timestamp=0.0,
        )
    )
    second_probe_result = processor.process(
        create_item(
            duration=4.0,
            timestamp=5.0,
        )
    )
    short_result = processor.process(
        create_item(
            duration=1.0,
            timestamp=10.0,
        )
    )

    assert [language for _, language in transcriber.calls] == [
        None,
        None,
        "en",
    ]

    assert first_probe_result.result.language == "en"
    assert first_probe_result.result.confidence == 0.96

    assert second_probe_result.result.language == "en"
    assert second_probe_result.result.confidence == 0.94

    assert short_result.result.language == "en"
    assert short_result.result.confidence is None


def test_established_language_probe_clears_competing_candidate() -> None:
    transcriber = FakeTranscriber(
        auto_results=[
            ("en", 0.96),
            ("ro", 0.97),
            ("en", 0.95),
        ],
    )
    settings = create_settings(
        initial_language="ro",
    )
    processor = create_processor(
        transcriber=transcriber,
        settings=settings,
    )

    processor.process(
        create_item(
            duration=4.0,
            timestamp=0.0,
        )
    )
    processor.process(
        create_item(
            duration=4.0,
            timestamp=5.0,
        )
    )
    processor.process(
        create_item(
            duration=4.0,
            timestamp=10.0,
        )
    )
    short_result = processor.process(
        create_item(
            duration=1.0,
            timestamp=15.0,
        )
    )

    assert [language for _, language in transcriber.calls] == [
        None,
        None,
        None,
        "ro",
    ]

    assert short_result.result.language == "ro"
    assert short_result.result.confidence is None


def test_different_competing_language_replaces_existing_candidate() -> None:
    transcriber = FakeTranscriber(
        auto_results=[
            ("en", 0.96),
            ("es", 0.95),
            ("es", 0.94),
        ],
    )
    settings = create_settings(
        initial_language="ro",
    )
    processor = create_processor(
        transcriber=transcriber,
        settings=settings,
    )

    processor.process(
        create_item(
            duration=4.0,
            timestamp=0.0,
        )
    )
    processor.process(
        create_item(
            duration=4.0,
            timestamp=5.0,
        )
    )

    first_short_result = processor.process(
        create_item(
            duration=1.0,
            timestamp=10.0,
        )
    )

    processor.process(
        create_item(
            duration=4.0,
            timestamp=12.0,
        )
    )

    second_short_result = processor.process(
        create_item(
            duration=1.0,
            timestamp=17.0,
        )
    )

    assert [language for _, language in transcriber.calls] == [
        None,
        None,
        "ro",
        None,
        "es",
    ]

    assert first_short_result.result.language == "ro"
    assert first_short_result.result.confidence is None

    assert second_short_result.result.language == "es"
    assert second_short_result.result.confidence is None


def test_low_confidence_competing_probe_accepts_auto_result_without_fallback() -> None:
    transcriber = FakeTranscriber(
        auto_results=[
            ("en", 0.84),
        ],
    )
    processor = create_processor(
        transcriber=transcriber,
        settings=create_settings(initial_language="ro"),
    )

    result = processor.process(
        create_item(
            duration=4.0,
            timestamp=0.0,
        )
    )

    assert [language for _, language in transcriber.calls] == [None]

    assert result.result.language == "en"
    assert result.result.confidence == 0.84


def test_low_confidence_competing_probe_preserves_existing_candidate() -> None:
    transcriber = FakeTranscriber(
        auto_results=[
            ("ro", 0.96),
            ("ro", 0.95),
            ("en", 0.90),
            ("en", 0.70),
            ("en", 0.91),
        ],
    )
    processor = create_processor(
        transcriber=transcriber,
        settings=create_settings(),
    )

    processor.process(create_item(duration=4.0, timestamp=0.0))
    processor.process(create_item(duration=4.0, timestamp=5.0))

    processor.process(create_item(duration=4.0, timestamp=10.0))
    weak_result = processor.process(create_item(duration=4.0, timestamp=15.0))
    processor.process(create_item(duration=4.0, timestamp=20.0))

    short_result = processor.process(create_item(duration=1.0, timestamp=25.0))

    assert weak_result.result.language == "en"
    assert weak_result.result.confidence == 0.70

    assert short_result.result.language == "en"
    assert short_result.result.confidence is None

    assert [language for _, language in transcriber.calls] == [
        None,
        None,
        None,
        None,
        None,
        "en",
    ]


def test_language_state_is_independent_per_source() -> None:
    transcriber = FakeTranscriber(
        auto_results=[
            ("ro", 0.96),
            ("en", 0.97),
            ("ro", 0.95),
            ("en", 0.96),
        ],
    )
    settings = create_settings()
    processor = create_processor(
        transcriber=transcriber,
        settings=settings,
    )

    processor.process(
        create_item(
            duration=4.0,
            timestamp=0.0,
            source=AudioSource.MICROPHONE,
        )
    )
    processor.process(
        create_item(
            duration=4.0,
            timestamp=0.0,
            source=AudioSource.SYSTEM_AUDIO,
        )
    )

    processor.process(
        create_item(
            duration=4.0,
            timestamp=5.0,
            source=AudioSource.MICROPHONE,
        )
    )
    processor.process(
        create_item(
            duration=4.0,
            timestamp=5.0,
            source=AudioSource.SYSTEM_AUDIO,
        )
    )

    microphone_result = processor.process(
        create_item(
            duration=1.0,
            timestamp=10.0,
            source=AudioSource.MICROPHONE,
        )
    )
    system_audio_result = processor.process(
        create_item(
            duration=1.0,
            timestamp=10.0,
            source=AudioSource.SYSTEM_AUDIO,
        )
    )

    assert microphone_result.result.language == "ro"
    assert microphone_result.result.confidence is None

    assert system_audio_result.result.language == "en"
    assert system_audio_result.result.confidence is None

    assert [language for _, language in transcriber.calls] == [
        None,
        None,
        None,
        None,
        "ro",
        "en",
    ]


def test_language_state_is_shared_across_processor_instances() -> None:
    settings = create_settings()

    state_store = AdaptiveLanguageStateStore(
        initial_language=settings.initial_language,
    )

    first_transcriber = FakeTranscriber(
        auto_results=[
            ("ro", 0.96),
            ("ro", 0.95),
        ],
    )
    second_transcriber = FakeTranscriber(
        auto_results=[],
    )

    first_processor = create_processor(
        transcriber=first_transcriber,
        settings=settings,
        state_store=state_store,
    )
    second_processor = create_processor(
        transcriber=second_transcriber,
        settings=settings,
        state_store=state_store,
    )

    first_processor.process(
        create_item(
            duration=4.0,
            timestamp=0.0,
            source=AudioSource.MICROPHONE,
        )
    )
    first_processor.process(
        create_item(
            duration=4.0,
            timestamp=5.0,
            source=AudioSource.MICROPHONE,
        )
    )

    result = second_processor.process(
        create_item(
            duration=1.0,
            timestamp=10.0,
            source=AudioSource.MICROPHONE,
        )
    )

    assert result.result.language == "ro"
    assert result.result.confidence is None

    assert [language for _, language in first_transcriber.calls] == [
        None,
        None,
    ]
    assert [language for _, language in second_transcriber.calls] == [
        "ro",
    ]


def test_logs_bootstrap_candidate_and_language_establishment(
    caplog: pytest.LogCaptureFixture,
) -> None:
    settings = create_settings()
    transcriber = FakeTranscriber(
        auto_results=[
            ("ro", 0.96),
            ("ro", 0.95),
        ],
    )
    processor = create_processor(
        transcriber=transcriber,
        settings=settings,
    )

    with caplog.at_level(
        logging.INFO,
        logger="app.transcription.adaptive_processor",
    ):
        processor.process(
            create_item(
                duration=4.0,
                timestamp=0.0,
            )
        )
        processor.process(
            create_item(
                duration=4.0,
                timestamp=5.0,
            )
        )

    assert "decision=candidate_created" in caplog.text
    assert "candidate_after=ro" in caplog.text
    assert "candidate_confirmations=1" in caplog.text

    assert "decision=language_established" in caplog.text
    assert "established_before=none" in caplog.text
    assert "established_after=ro" in caplog.text


def test_logs_low_confidence_probe(
    caplog: pytest.LogCaptureFixture,
) -> None:
    settings = create_settings(
        initial_language="ro",
    )
    transcriber = FakeTranscriber(
        auto_results=[
            ("en", 0.84),
        ],
    )
    processor = create_processor(
        transcriber=transcriber,
        settings=settings,
    )

    with caplog.at_level(
        logging.INFO,
        logger="app.transcription.adaptive_processor",
    ):
        processor.process(
            create_item(
                duration=4.0,
            )
        )

    assert "decision=low_confidence_probe" in caplog.text
    assert "selected_language=auto" in caplog.text
    assert "established_before=ro" in caplog.text
    assert "established_after=ro" in caplog.text
    assert "candidate_before=none" in caplog.text
    assert "candidate_after=none" in caplog.text


def test_logs_confirmed_language_switch(
    caplog: pytest.LogCaptureFixture,
) -> None:
    settings = create_settings(
        initial_language="ro",
    )
    transcriber = FakeTranscriber(
        auto_results=[
            ("en", 0.96),
            ("en", 0.95),
        ],
    )
    processor = create_processor(
        transcriber=transcriber,
        settings=settings,
    )

    with caplog.at_level(
        logging.INFO,
        logger="app.transcription.adaptive_processor",
    ):
        processor.process(
            create_item(
                duration=4.0,
                timestamp=0.0,
            )
        )
        processor.process(
            create_item(
                duration=4.0,
                timestamp=5.0,
            )
        )

    assert "decision=candidate_created" in caplog.text
    assert "candidate_after=en" in caplog.text

    assert "decision=language_switched" in caplog.text
    assert "established_before=ro" in caplog.text
    assert "established_after=en" in caplog.text


def test_low_confidence_conflicting_probe_accepts_auto_result_without_fallback() -> None:
    transcriber = FakeTranscriber(
        auto_results=[
            ("ro", 0.96),
            ("ro", 0.95),
            ("en", 0.72),
        ],
    )
    processor = create_processor(
        transcriber=transcriber,
        settings=create_settings(),
    )

    processor.process(create_item(duration=4.0, timestamp=0.0))
    processor.process(create_item(duration=4.0, timestamp=5.0))

    result = processor.process(create_item(duration=5.0, timestamp=10.0))

    assert result.result.language == "en"
    assert result.result.confidence == 0.72

    assert [language for _, language in transcriber.calls] == [
        None,
        None,
        None,
    ]


def test_low_confidence_probe_preserves_existing_candidate() -> None:
    transcriber = FakeTranscriber(
        auto_results=[
            ("ro", 0.96),
            ("ro", 0.95),
            ("en", 0.87),
            ("en", 0.64),
            ("en", 0.90),
        ],
    )
    processor = create_processor(
        transcriber=transcriber,
        settings=create_settings(),
    )

    processor.process(create_item(duration=4.0, timestamp=0.0))
    processor.process(create_item(duration=4.0, timestamp=5.0))

    processor.process(create_item(duration=4.0, timestamp=10.0))
    processor.process(create_item(duration=4.0, timestamp=15.0))
    processor.process(create_item(duration=4.0, timestamp=20.0))

    short_result = processor.process(create_item(duration=1.0, timestamp=25.0))

    assert short_result.result.language == "en"
    assert short_result.result.confidence is None

    assert [language for _, language in transcriber.calls] == [
        None,
        None,
        None,
        None,
        None,
        "en",
    ]


def test_low_confidence_third_language_does_not_replace_candidate() -> None:
    transcriber = FakeTranscriber(
        auto_results=[
            ("ro", 0.96),
            ("ro", 0.95),
            ("en", 0.90),
            ("pt", 0.70),
            ("en", 0.91),
        ],
    )
    processor = create_processor(
        transcriber=transcriber,
        settings=create_settings(),
    )

    processor.process(create_item(duration=4.0, timestamp=0.0))
    processor.process(create_item(duration=4.0, timestamp=5.0))

    processor.process(create_item(duration=4.0, timestamp=10.0))
    processor.process(create_item(duration=4.0, timestamp=15.0))
    processor.process(create_item(duration=4.0, timestamp=20.0))

    short_result = processor.process(create_item(duration=1.0, timestamp=25.0))

    assert short_result.result.language == "en"
    assert short_result.result.confidence is None


def test_strong_established_language_probe_clears_existing_candidate() -> None:
    transcriber = FakeTranscriber(
        auto_results=[
            ("ro", 0.96),
            ("ro", 0.95),
            ("en", 0.90),
            ("ro", 0.93),
            ("en", 0.91),
            ("en", 0.92),
        ],
    )
    processor = create_processor(
        transcriber=transcriber,
        settings=create_settings(),
    )

    processor.process(create_item(duration=4.0, timestamp=0.0))
    processor.process(create_item(duration=4.0, timestamp=5.0))

    processor.process(create_item(duration=4.0, timestamp=10.0))

    processor.process(create_item(duration=4.0, timestamp=15.0))

    processor.process(create_item(duration=4.0, timestamp=20.0))
    processor.process(create_item(duration=4.0, timestamp=25.0))

    short_result = processor.process(create_item(duration=1.0, timestamp=30.0))

    assert short_result.result.language == "en"
    assert short_result.result.confidence is None


def test_strong_competing_language_replaces_existing_candidate() -> None:
    transcriber = FakeTranscriber(
        auto_results=[
            ("ro", 0.96),
            ("ro", 0.95),
            ("en", 0.90),
            ("de", 0.91),
            ("de", 0.92),
        ],
    )
    processor = create_processor(
        transcriber=transcriber,
        settings=create_settings(),
    )

    processor.process(create_item(duration=4.0, timestamp=0.0))
    processor.process(create_item(duration=4.0, timestamp=5.0))

    processor.process(create_item(duration=4.0, timestamp=10.0))
    processor.process(create_item(duration=4.0, timestamp=15.0))
    processor.process(create_item(duration=4.0, timestamp=20.0))

    short_result = processor.process(create_item(duration=1.0, timestamp=25.0))

    assert short_result.result.language == "de"
    assert short_result.result.confidence is None


def test_same_candidate_within_max_gap_confirms_language_switch() -> None:
    transcriber = FakeTranscriber(
        auto_results=[
            ("ro", 0.96),
            ("ro", 0.95),
            ("en", 0.90),
            ("en", 0.91),
        ],
    )
    processor = create_processor(
        transcriber=transcriber,
        settings=create_settings(
            candidate_max_gap_seconds=30.0,
        ),
    )

    processor.process(create_item(duration=4.0, timestamp=0.0))
    processor.process(create_item(duration=4.0, timestamp=5.0))

    processor.process(create_item(duration=4.0, timestamp=10.0))
    processor.process(create_item(duration=4.0, timestamp=20.0))

    result = processor.process(create_item(duration=1.0, timestamp=25.0))

    assert result.result.language == "en"


def test_same_candidate_after_max_gap_restarts_confirmation() -> None:
    transcriber = FakeTranscriber(
        auto_results=[
            ("ro", 0.96),
            ("ro", 0.95),
            ("en", 0.90),
            ("en", 0.91),
        ],
    )
    processor = create_processor(
        transcriber=transcriber,
        settings=create_settings(candidate_max_gap_seconds=30.0),
    )

    processor.process(create_item(duration=4.0, timestamp=0.0))
    processor.process(create_item(duration=4.0, timestamp=5.0))

    # First strong English evidence ends at 14.0.
    processor.process(create_item(duration=4.0, timestamp=10.0))

    # 50.0 - 14.0 = 36 seconds, so the English candidate is stale.
    processor.process(create_item(duration=4.0, timestamp=50.0))

    short_result = processor.process(create_item(duration=1.0, timestamp=55.0))

    # English must not have switched after the stale confirmation.
    assert short_result.result.language == "ro"


def test_same_candidate_within_max_gap_confirms_switch() -> None:
    transcriber = FakeTranscriber(
        auto_results=[
            ("ro", 0.96),
            ("ro", 0.95),
            ("en", 0.90),
            ("en", 0.91),
        ],
    )
    processor = create_processor(
        transcriber=transcriber,
        settings=create_settings(candidate_max_gap_seconds=30.0),
    )

    processor.process(create_item(duration=4.0, timestamp=0.0))
    processor.process(create_item(duration=4.0, timestamp=5.0))

    # English evidence ends at 14.0.
    processor.process(create_item(duration=4.0, timestamp=10.0))

    # 20.0 - 14.0 = 6 seconds, so it confirms.
    processor.process(create_item(duration=4.0, timestamp=20.0))

    short_result = processor.process(create_item(duration=1.0, timestamp=25.0))

    assert short_result.result.language == "en"


def test_low_confidence_probe_does_not_refresh_candidate_lifetime() -> None:
    transcriber = FakeTranscriber(
        auto_results=[
            ("ro", 0.96),
            ("ro", 0.95),
            ("en", 0.90),
            ("en", 0.60),
            ("en", 0.91),
        ],
    )
    processor = create_processor(
        transcriber=transcriber,
        settings=create_settings(candidate_max_gap_seconds=30.0),
    )

    processor.process(create_item(duration=4.0, timestamp=0.0))
    processor.process(create_item(duration=4.0, timestamp=5.0))

    # Strong English evidence ends at 14.0.
    processor.process(create_item(duration=4.0, timestamp=10.0))

    # Weak English evidence must not refresh candidate age.
    processor.process(create_item(duration=4.0, timestamp=30.0))

    # Gap is still measured from 14.0:
    # 50.0 - 14.0 = 36 seconds.
    processor.process(create_item(duration=4.0, timestamp=50.0))

    short_result = processor.process(create_item(duration=1.0, timestamp=55.0))

    assert short_result.result.language == "ro"


def test_unknown_language_candidate_expires_before_confirmation() -> None:
    transcriber = FakeTranscriber(
        auto_results=[
            ("ro", 0.96),
            ("ro", 0.95),
            ("ro", 0.94),
        ],
    )
    processor = create_processor(
        transcriber=transcriber,
        settings=create_settings(candidate_max_gap_seconds=30.0),
    )

    # First candidate ends at 4.0.
    processor.process(create_item(duration=4.0, timestamp=0.0))

    # Too far away: restart candidate instead of establishing.
    processor.process(create_item(duration=4.0, timestamp=40.0))

    # Now close enough to the restarted candidate.
    processor.process(create_item(duration=4.0, timestamp=50.0))

    short_result = processor.process(create_item(duration=1.0, timestamp=55.0))

    assert short_result.result.language == "ro"
    assert short_result.result.confidence is None
