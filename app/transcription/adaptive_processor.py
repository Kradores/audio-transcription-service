from __future__ import annotations

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
            return self._process_unknown_language(item, state)

        if item.segment.duration < self._settings.min_probe_duration_seconds:
            result = self._transcriber.transcribe(
                item.segment,
                language=state.established_language,
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

        elif (
            result.confidence is not None
            and result.confidence >= self._settings.switch_probability_threshold
        ):
            if state.candidate_language == result.language:
                state.candidate_confirmations += 1
            else:
                state.candidate_language = result.language
                state.candidate_confirmations = 1

            if state.candidate_confirmations >= self._settings.switch_confirmations:
                state.established_language = result.language
                state.candidate_language = None
                state.candidate_confirmations = 0

        else:
            state.candidate_language = None
            state.candidate_confirmations = 0

            result = self._transcriber.transcribe(
                item.segment,
                language=state.established_language,
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
        result = self._transcriber.transcribe(
            item.segment,
            language=None,
        )

        if (
            item.segment.duration >= self._settings.min_probe_duration_seconds
            and result.confidence is not None
            and result.confidence >= self._settings.switch_probability_threshold
        ):
            state.established_language = result.language

        return SourcedTranscriptionResult(
            source=item.source,
            result=result,
        )
