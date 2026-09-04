from __future__ import annotations

import logging
from enum import StrEnum

from app.core.config.models import AdaptiveTranscriptionLanguageSettings
from app.transcription.adaptive_language_state import (
    AdaptiveLanguageState,
    AdaptiveLanguageStateStore,
)
from app.transcription.contracts import (
    SourcedTranscriptionResult,
    TranscriptionWorkItem,
)
from app.transcription.protocols import Transcriber

logger = logging.getLogger(__name__)


class _AdaptiveLanguageDecision(StrEnum):
    UNKNOWN_SHORT = "unknown_short"
    UNKNOWN_PROBE_INSUFFICIENT_CONFIDENCE = "unknown_probe_insufficient_confidence"
    LANGUAGE_ESTABLISHED = "language_established"
    ESTABLISHED_SHORT = "established_short"
    PROBE_CONFIRMED_ESTABLISHED = "probe_confirmed_established"
    CANDIDATE_CLEARED = "candidate_cleared"
    CANDIDATE_CREATED = "candidate_created"
    CANDIDATE_CONFIRMED = "candidate_confirmed"
    CANDIDATE_REPLACED = "candidate_replaced"
    LANGUAGE_SWITCHED = "language_switched"
    LOW_CONFIDENCE_FALLBACK = "low_confidence_fallback"


def _log_decision(
    *,
    item: TranscriptionWorkItem,
    decision: _AdaptiveLanguageDecision,
    established_before: str | None,
    established_after: str | None,
    candidate_before: str | None,
    candidate_after: str | None,
    candidate_confirmations: int,
    selected_language: str | None,
    probe: bool,
    detected_language: str | None = None,
    detected_probability: float | None = None,
) -> None:
    logger.info(
        "adaptive language decision "
        "source=%s start=%.3f duration=%.3f "
        "decision=%s probe=%s "
        "established_before=%s established_after=%s "
        "candidate_before=%s candidate_after=%s "
        "candidate_confirmations=%d "
        "selected_language=%s "
        "detected_language=%s detected_probability=%s",
        item.source.value,
        item.segment.timestamp,
        item.segment.duration,
        decision.value,
        "true" if probe else "false",
        established_before or "none",
        established_after or "none",
        candidate_before or "none",
        candidate_after or "none",
        candidate_confirmations,
        selected_language or "auto",
        detected_language or "none",
        (f"{detected_probability:.3f}" if detected_probability is not None else "none"),
    )


class AdaptiveTranscriptionProcessor:
    """Apply per-source adaptive transcription language policy."""

    def __init__(
        self,
        *,
        transcriber: Transcriber,
        settings: AdaptiveTranscriptionLanguageSettings,
        state_store: AdaptiveLanguageStateStore,
    ) -> None:
        self._transcriber = transcriber
        self._settings = settings
        self._state_store = state_store

    def process(
        self,
        item: TranscriptionWorkItem,
    ) -> SourcedTranscriptionResult:
        state = self._state_store.state_for(item.source)

        if state.established_language is None:
            return self._process_unknown_language(
                item,
                state,
            )

        established_before = state.established_language
        candidate_before = state.candidate_language

        if item.segment.duration < self._settings.min_probe_duration_seconds:
            result = self._transcriber.transcribe(
                item.segment,
                language=state.established_language,
            )

            _log_decision(
                item=item,
                decision=_AdaptiveLanguageDecision.ESTABLISHED_SHORT,
                established_before=established_before,
                established_after=state.established_language,
                candidate_before=candidate_before,
                candidate_after=state.candidate_language,
                candidate_confirmations=state.candidate_confirmations,
                selected_language=state.established_language,
                probe=False,
            )

            return SourcedTranscriptionResult(
                source=item.source,
                result=result,
            )

        result = self._transcriber.transcribe(
            item.segment,
            language=None,
        )

        if result.language == state.established_language:
            state.candidate_language = None
            state.candidate_confirmations = 0

            decision = (
                _AdaptiveLanguageDecision.CANDIDATE_CLEARED
                if candidate_before is not None
                else _AdaptiveLanguageDecision.PROBE_CONFIRMED_ESTABLISHED
            )

            _log_decision(
                item=item,
                decision=decision,
                established_before=established_before,
                established_after=state.established_language,
                candidate_before=candidate_before,
                candidate_after=state.candidate_language,
                candidate_confirmations=state.candidate_confirmations,
                selected_language=None,
                probe=True,
                detected_language=result.language,
                detected_probability=result.confidence,
            )

        elif (
            result.confidence is not None
            and result.confidence >= self._settings.switch_probability_threshold
        ):
            if state.candidate_language == result.language:
                state.candidate_confirmations += 1
                decision = _AdaptiveLanguageDecision.CANDIDATE_CONFIRMED
            else:
                decision = (
                    _AdaptiveLanguageDecision.CANDIDATE_REPLACED
                    if state.candidate_language is not None
                    else _AdaptiveLanguageDecision.CANDIDATE_CREATED
                )

                state.candidate_language = result.language
                state.candidate_confirmations = 1

            if state.candidate_confirmations >= self._settings.switch_confirmations:
                state.established_language = result.language
                state.candidate_language = None
                state.candidate_confirmations = 0
                decision = _AdaptiveLanguageDecision.LANGUAGE_SWITCHED

            _log_decision(
                item=item,
                decision=decision,
                established_before=established_before,
                established_after=state.established_language,
                candidate_before=candidate_before,
                candidate_after=state.candidate_language,
                candidate_confirmations=state.candidate_confirmations,
                selected_language=None,
                probe=True,
                detected_language=result.language,
                detected_probability=result.confidence,
            )

        else:
            detected_language = result.language
            detected_probability = result.confidence

            state.candidate_language = None
            state.candidate_confirmations = 0

            result = self._transcriber.transcribe(
                item.segment,
                language=state.established_language,
            )

            _log_decision(
                item=item,
                decision=_AdaptiveLanguageDecision.LOW_CONFIDENCE_FALLBACK,
                established_before=established_before,
                established_after=state.established_language,
                candidate_before=candidate_before,
                candidate_after=state.candidate_language,
                candidate_confirmations=state.candidate_confirmations,
                selected_language=state.established_language,
                probe=True,
                detected_language=detected_language,
                detected_probability=detected_probability,
            )

        return SourcedTranscriptionResult(
            source=item.source,
            result=result,
        )

    def _process_unknown_language(
        self,
        item: TranscriptionWorkItem,
        state: AdaptiveLanguageState,
    ) -> SourcedTranscriptionResult:
        established_before = state.established_language
        candidate_before = state.candidate_language

        result = self._transcriber.transcribe(
            item.segment,
            language=None,
        )

        if item.segment.duration < self._settings.min_probe_duration_seconds:
            _log_decision(
                item=item,
                decision=_AdaptiveLanguageDecision.UNKNOWN_SHORT,
                established_before=established_before,
                established_after=state.established_language,
                candidate_before=candidate_before,
                candidate_after=state.candidate_language,
                candidate_confirmations=state.candidate_confirmations,
                selected_language=None,
                probe=False,
                detected_language=result.language,
                detected_probability=result.confidence,
            )

            return SourcedTranscriptionResult(
                source=item.source,
                result=result,
            )

        if (
            result.confidence is not None
            and result.confidence >= self._settings.switch_probability_threshold
        ):
            state.established_language = result.language

            decision = _AdaptiveLanguageDecision.LANGUAGE_ESTABLISHED
        else:
            decision = _AdaptiveLanguageDecision.UNKNOWN_PROBE_INSUFFICIENT_CONFIDENCE

        _log_decision(
            item=item,
            decision=decision,
            established_before=established_before,
            established_after=state.established_language,
            candidate_before=candidate_before,
            candidate_after=state.candidate_language,
            candidate_confirmations=state.candidate_confirmations,
            selected_language=None,
            probe=True,
            detected_language=result.language,
            detected_probability=result.confidence,
        )

        return SourcedTranscriptionResult(
            source=item.source,
            result=result,
        )
