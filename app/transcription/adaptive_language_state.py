from __future__ import annotations

from dataclasses import dataclass
from threading import Lock

from app.transcription.contracts import AudioSource


@dataclass
class AdaptiveLanguageState:
    established_language: str | None
    candidate_language: str | None = None
    candidate_confirmations: int = 0


class AdaptiveLanguageStateStore:
    """Hold conversation-scoped adaptive language state per audio source."""

    def __init__(
        self,
        *,
        initial_language: str | None,
    ) -> None:
        self._initial_language = initial_language
        self._states: dict[AudioSource, AdaptiveLanguageState] = {}
        self._lock = Lock()

    def state_for(
        self,
        source: AudioSource,
    ) -> AdaptiveLanguageState:
        with self._lock:
            state = self._states.get(source)

            if state is None:
                state = AdaptiveLanguageState(
                    established_language=self._initial_language,
                )
                self._states[source] = state

            return state
