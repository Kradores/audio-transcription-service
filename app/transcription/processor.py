from __future__ import annotations

from app.core.config.models import (
    AutoTranscriptionLanguageSettings,
    FixedTranscriptionLanguageSettings,
)
from app.transcription.contracts import (
    SourcedTranscriptionResult,
    TranscriptionWorkItem,
)
from app.transcription.protocols import Transcriber


class TranscriptionProcessorImpl:
    """Apply configured transcription policy to sourced work items."""

    def __init__(
        self,
        *,
        transcriber: Transcriber,
        language_settings: (AutoTranscriptionLanguageSettings | FixedTranscriptionLanguageSettings),
    ) -> None:
        self._transcriber = transcriber
        self._language_settings = language_settings

    def process(
        self,
        item: TranscriptionWorkItem,
    ) -> SourcedTranscriptionResult:
        language: str | None

        if isinstance(
            self._language_settings,
            FixedTranscriptionLanguageSettings,
        ):
            language = self._language_settings.language
        else:
            language = None

        result = self._transcriber.transcribe(
            item.segment,
            language=language,
        )

        return SourcedTranscriptionResult(
            source=item.source,
            result=result,
        )
