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
) -> AdaptiveTranscriptionLanguageSettings:
    return AdaptiveTranscriptionLanguageSettings(
        mode=TranscriptionLanguageMode.ADAPTIVE,
        initial_language=initial_language,
        min_probe_duration_seconds=3.0,
        switch_probability_threshold=0.85,
        switch_confirmations=2,
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


def test_high_confidence_probe_establishes_language_for_next_short_segment() -> None:
    transcriber = FakeTranscriber(
        auto_results=[
            ("ro", 0.95),
        ],
    )
    settings = create_settings()
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

    assert probe_result.result.language == "ro"
    assert probe_result.result.confidence == 0.95

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


def test_low_confidence_competing_probe_falls_back_to_established_language() -> None:
    transcriber = FakeTranscriber(
        auto_results=[
            ("bg", 0.55),
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
            timestamp=0.0,
        )
    )

    assert [language for _, language in transcriber.calls] == [
        None,
        "ro",
    ]

    assert result.result.language == "ro"
    assert result.result.confidence is None


def test_low_confidence_competing_probe_clears_existing_candidate() -> None:
    transcriber = FakeTranscriber(
        auto_results=[
            ("en", 0.96),
            ("bg", 0.55),
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

    # First strong English probe creates candidate=en/1.
    processor.process(
        create_item(
            duration=4.0,
            timestamp=0.0,
        )
    )

    # Weak Bulgarian probe must clear the English candidate and
    # fall back to explicit Romanian transcription.
    weak_probe_result = processor.process(
        create_item(
            duration=4.0,
            timestamp=5.0,
        )
    )

    # This strong English probe must start again at candidate=en/1,
    # not complete an old en/2 sequence.
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
        "ro",
        None,
        "ro",
    ]

    assert weak_probe_result.result.language == "ro"
    assert weak_probe_result.result.confidence is None

    assert short_result.result.language == "ro"
    assert short_result.result.confidence is None


def test_language_state_is_independent_per_source() -> None:
    transcriber = FakeTranscriber(
        auto_results=[
            ("ro", 0.96),
            ("en", 0.97),
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

    microphone_result = processor.process(
        create_item(
            duration=1.0,
            timestamp=5.0,
            source=AudioSource.MICROPHONE,
        )
    )
    system_audio_result = processor.process(
        create_item(
            duration=1.0,
            timestamp=5.0,
            source=AudioSource.SYSTEM_AUDIO,
        )
    )

    assert [language for _, language in transcriber.calls] == [
        None,
        None,
        "ro",
        "en",
    ]

    assert microphone_result.source == AudioSource.MICROPHONE
    assert microphone_result.result.language == "ro"
    assert microphone_result.result.confidence is None

    assert system_audio_result.source == AudioSource.SYSTEM_AUDIO
    assert system_audio_result.result.language == "en"
    assert system_audio_result.result.confidence is None


def test_language_state_is_shared_across_processor_instances() -> None:
    settings = create_settings()

    state_store = AdaptiveLanguageStateStore(
        initial_language=settings.initial_language,
    )

    first_transcriber = FakeTranscriber(
        auto_results=[
            ("ro", 0.96),
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

    result = second_processor.process(
        create_item(
            duration=1.0,
            timestamp=5.0,
            source=AudioSource.MICROPHONE,
        )
    )

    assert [language for _, language in first_transcriber.calls] == [
        None,
    ]
    assert [language for _, language in second_transcriber.calls] == [
        "ro",
    ]

    assert result.source == AudioSource.MICROPHONE
    assert result.result.language == "ro"
    assert result.result.confidence is None


def test_logs_language_establishment(
    caplog: pytest.LogCaptureFixture,
) -> None:
    settings = create_settings()
    transcriber = FakeTranscriber(
        auto_results=[
            ("ro", 0.96),
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

    assert "decision=language_established" in caplog.text
    assert "established_before=none" in caplog.text
    assert "established_after=ro" in caplog.text
    assert "detected_language=ro" in caplog.text
    assert "detected_probability=0.960" in caplog.text


def test_logs_low_confidence_fallback(
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

    assert "decision=low_confidence_fallback" in caplog.text
    assert "established_before=ro" in caplog.text
    assert "established_after=ro" in caplog.text
    assert "selected_language=ro" in caplog.text
    assert "detected_language=en" in caplog.text
    assert "detected_probability=0.840" in caplog.text


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
