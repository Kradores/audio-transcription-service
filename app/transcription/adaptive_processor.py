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
    CANDIDATE_RESTARTED = "candidate_restarted"
    LANGUAGE_SWITCHED = "language_switched"
    LOW_CONFIDENCE_PROBE = "low_confidence_probe"


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

    @staticmethod
    def _clear_candidate(state: AdaptiveLanguageState) -> None:
        state.candidate_language = None
        state.candidate_confirmations = 0
        state.candidate_last_strong_evidence_end = None

    @staticmethod
    def _start_candidate(
        state: AdaptiveLanguageState,
        *,
        language: str,
        evidence_end: float,
    ) -> None:
        state.candidate_language = language
        state.candidate_confirmations = 1
        state.candidate_last_strong_evidence_end = evidence_end

    @staticmethod
    def _confirm_candidate(
        state: AdaptiveLanguageState,
        *,
        evidence_end: float,
    ) -> None:
        state.candidate_confirmations += 1
        state.candidate_last_strong_evidence_end = evidence_end

    def _candidate_is_expired(
        self,
        *,
        state: AdaptiveLanguageState,
        item: TranscriptionWorkItem,
    ) -> bool:
        if state.candidate_language is None:
            return False

        previous_evidence_end = state.candidate_last_strong_evidence_end

        # A candidate without an evidence timestamp is incomplete state.
        # Treat it conservatively as stale instead of allowing it to be
        # confirmed indefinitely.
        if previous_evidence_end is None:
            return True

        gap = max(
            0.0,
            item.segment.timestamp - previous_evidence_end,
        )

        return gap > self._settings.candidate_max_gap_seconds

    def _apply_strong_candidate_evidence(
        self,
        *,
        state: AdaptiveLanguageState,
        item: TranscriptionWorkItem,
        language: str,
    ) -> _AdaptiveLanguageDecision:
        evidence_end = item.segment.timestamp + item.segment.duration

        if self._candidate_is_expired(
            state=state,
            item=item,
        ):
            expired_language = state.candidate_language

            self._clear_candidate(state)
            self._start_candidate(
                state,
                language=language,
                evidence_end=evidence_end,
            )

            if expired_language == language:
                return _AdaptiveLanguageDecision.CANDIDATE_RESTARTED

            return _AdaptiveLanguageDecision.CANDIDATE_CREATED

        if state.candidate_language == language:
            self._confirm_candidate(
                state,
                evidence_end=evidence_end,
            )
            return _AdaptiveLanguageDecision.CANDIDATE_CONFIRMED

        if state.candidate_language is not None:
            self._start_candidate(
                state,
                language=language,
                evidence_end=evidence_end,
            )
            return _AdaptiveLanguageDecision.CANDIDATE_REPLACED

        self._start_candidate(
            state,
            language=language,
            evidence_end=evidence_end,
        )
        return _AdaptiveLanguageDecision.CANDIDATE_CREATED

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

        has_strong_evidence = (
            result.confidence is not None
            and result.confidence >= self._settings.switch_probability_threshold
        )

        if not has_strong_evidence:
            # ADR-047:
            # Low-confidence automatic evidence is accepted as the transcript
            # result but does not mutate persistent language state.
            _log_decision(
                item=item,
                decision=_AdaptiveLanguageDecision.LOW_CONFIDENCE_PROBE,
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

        elif result.language == state.established_language:
            # Strong evidence for the currently established language cancels
            # any competing candidate, including its evidence timestamp.
            self._clear_candidate(state)

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

        else:
            decision = self._apply_strong_candidate_evidence(
                state=state,
                item=item,
                language=result.language,
            )

            if state.candidate_confirmations >= self._settings.switch_confirmations:
                state.established_language = result.language
                self._clear_candidate(state)
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

        has_strong_evidence = (
            result.confidence is not None
            and result.confidence >= self._settings.switch_probability_threshold
        )

        if has_strong_evidence:
            decision = self._apply_strong_candidate_evidence(
                state=state,
                item=item,
                language=result.language,
            )

            if state.candidate_confirmations >= self._settings.switch_confirmations:
                state.established_language = result.language
                self._clear_candidate(state)
                decision = _AdaptiveLanguageDecision.LANGUAGE_ESTABLISHED

        else:
            # Weak evidence neither establishes a language nor mutates or
            # refreshes an existing bootstrap candidate.
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
