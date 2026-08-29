from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Protocol

type Sleep = Callable[[float], Awaitable[None]]

DEFAULT_PORTAUDIO_SETTLE_SECONDS = 0.5

logger = logging.getLogger(__name__)


class PortAudioRefreshParticipant(Protocol):
    """One source participating in a process-wide PortAudio refresh."""

    def prepare_for_portaudio_refresh(self) -> None:
        """Dispose this source's current native PortAudio session."""

    async def restore_after_portaudio_refresh(self) -> None:
        """Attempt to restore this source after process-wide teardown."""


class PortAudioRefreshRequester(Protocol):
    def signal_refresh_requested(self) -> None:
        """Record that a process-wide refresh is required."""

    async def request_refresh(self) -> None:
        """Process any pending coordinated PortAudio refresh."""


class PortAudioRefreshCoordinator:
    def __init__(
        self,
        *,
        sleep: Sleep = asyncio.sleep,
        settle_seconds: float = DEFAULT_PORTAUDIO_SETTLE_SECONDS,
    ) -> None:
        self._sleep = sleep
        self._settle_seconds = settle_seconds

        self._participants: list[PortAudioRefreshParticipant] = []
        self._refresh_lock = asyncio.Lock()

        self._requested_generation = 0
        self._completed_generation = 0

    def register(
        self,
        participant: PortAudioRefreshParticipant,
    ) -> None:
        self._participants.append(participant)

    def signal_refresh_requested(self) -> None:
        self._requested_generation += 1

    async def request_refresh(self) -> None:
        request_generation = self._requested_generation

        if request_generation <= self._completed_generation:
            return

        async with self._refresh_lock:
            if self._requested_generation <= self._completed_generation:
                return

            refresh_generation = self._requested_generation

            logger.info(
                "process-wide PortAudio refresh started generation=%d",
                refresh_generation,
            )

            self._dispose_all_participants()

            stable_generation = await self._wait_until_notifications_settle()

            await self._restore_all_participants()

            self._completed_generation = stable_generation

            logger.info(
                "process-wide PortAudio refresh completed generation=%d",
                stable_generation,
            )

    def _dispose_all_participants(self) -> None:
        errors: list[Exception] = []

        for participant in self._participants:
            try:
                participant.prepare_for_portaudio_refresh()
            except Exception as exc:
                errors.append(exc)

        if errors:
            raise ExceptionGroup(
                "PortAudio refresh teardown failed",
                errors,
            )

    async def _wait_until_notifications_settle(self) -> int:
        while True:
            generation = self._requested_generation

            await self._sleep(self._settle_seconds)

            if generation == self._requested_generation:
                return generation

    async def _restore_all_participants(self) -> None:
        for participant in self._participants:
            try:
                await participant.restore_after_portaudio_refresh()
            except (LookupError, OSError) as exc:
                logger.warning(
                    "PortAudio refresh participant restore failed; "
                    "source-local recovery will continue "
                    "error_type=%s error=%r",
                    type(exc).__name__,
                    exc,
                )
