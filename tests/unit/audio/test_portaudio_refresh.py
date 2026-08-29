from __future__ import annotations

import asyncio
from collections.abc import Callable

import pytest

from app.audio.portaudio_refresh import PortAudioRefreshCoordinator


class FakeParticipant:
    def __init__(
        self,
        name: str,
        events: list[str],
        *,
        restore_error: Exception | None = None,
    ) -> None:
        self._name = name
        self._events = events
        self._restore_error = restore_error

    def prepare_for_portaudio_refresh(self) -> None:
        self._events.append(f"{self._name}:dispose")

    async def restore_after_portaudio_refresh(self) -> None:
        self._events.append(f"{self._name}:restore")

        if self._restore_error is not None:
            raise self._restore_error


class ControlledSleep:
    def __init__(self) -> None:
        self.calls: list[float] = []
        self._waiters: asyncio.Queue[asyncio.Future[None]] = asyncio.Queue()

    async def __call__(self, delay: float) -> None:
        self.calls.append(delay)

        future = asyncio.get_running_loop().create_future()
        await self._waiters.put(future)

        await future

    async def release_next(self) -> None:
        future = await self._waiters.get()

        if not future.done():
            future.set_result(None)

        await asyncio.sleep(0)


async def _wait_until(
    condition: Callable[[], bool],
) -> None:
    for _ in range(100):
        if condition():
            return

        await asyncio.sleep(0)

    raise AssertionError("condition was not reached")


@pytest.mark.anyio
async def test_refresh_disposes_all_participants_before_any_restore() -> None:
    events: list[str] = []

    coordinator = PortAudioRefreshCoordinator(
        settle_seconds=0.0,
    )

    coordinator.register(
        FakeParticipant("system", events),
    )
    coordinator.register(
        FakeParticipant("microphone", events),
    )

    coordinator.signal_refresh_requested()
    await coordinator.request_refresh()

    assert events == [
        "system:dispose",
        "microphone:dispose",
        "system:restore",
        "microphone:restore",
    ]


@pytest.mark.anyio
async def test_refresh_waits_for_settle_after_all_participants_are_disposed() -> None:
    events: list[str] = []
    sleep = ControlledSleep()

    coordinator = PortAudioRefreshCoordinator(
        sleep=sleep,
        settle_seconds=0.25,
    )

    coordinator.register(
        FakeParticipant("system", events),
    )
    coordinator.register(
        FakeParticipant("microphone", events),
    )

    coordinator.signal_refresh_requested()
    task = asyncio.create_task(
        coordinator.request_refresh(),
    )

    await _wait_until(
        lambda: sleep.calls == [0.25],
    )

    assert events == [
        "system:dispose",
        "microphone:dispose",
    ]

    await sleep.release_next()
    await task

    assert events == [
        "system:dispose",
        "microphone:dispose",
        "system:restore",
        "microphone:restore",
    ]


@pytest.mark.anyio
async def test_refresh_request_during_settle_extends_same_refresh() -> None:
    events: list[str] = []
    sleep = ControlledSleep()

    coordinator = PortAudioRefreshCoordinator(
        sleep=sleep,
        settle_seconds=0.25,
    )

    coordinator.register(
        FakeParticipant("system", events),
    )
    coordinator.register(
        FakeParticipant("microphone", events),
    )

    coordinator.signal_refresh_requested()
    first = asyncio.create_task(
        coordinator.request_refresh(),
    )

    await _wait_until(
        lambda: len(sleep.calls) == 1,
    )

    coordinator.signal_refresh_requested()
    second = asyncio.create_task(
        coordinator.request_refresh(),
    )

    await sleep.release_next()

    await _wait_until(
        lambda: len(sleep.calls) == 2,
    )

    assert events == [
        "system:dispose",
        "microphone:dispose",
    ]

    await sleep.release_next()

    await first
    await second

    assert events == [
        "system:dispose",
        "microphone:dispose",
        "system:restore",
        "microphone:restore",
    ]


@pytest.mark.anyio
async def test_multiple_requests_during_settle_cause_one_teardown() -> None:
    events: list[str] = []
    sleep = ControlledSleep()

    coordinator = PortAudioRefreshCoordinator(
        sleep=sleep,
        settle_seconds=0.25,
    )

    coordinator.register(
        FakeParticipant("system", events),
    )
    coordinator.register(
        FakeParticipant("microphone", events),
    )

    coordinator.signal_refresh_requested()
    first = asyncio.create_task(
        coordinator.request_refresh(),
    )

    await _wait_until(
        lambda: len(sleep.calls) == 1,
    )

    async def trigger_refresh() -> None:
        coordinator.signal_refresh_requested()
        await coordinator.request_refresh()

    additional = [asyncio.create_task(trigger_refresh()) for _ in range(3)]

    await sleep.release_next()

    await _wait_until(
        lambda: len(sleep.calls) == 2,
    )

    await sleep.release_next()

    await first
    await asyncio.gather(*additional)

    assert events.count("system:dispose") == 1
    assert events.count("microphone:dispose") == 1
    assert events.count("system:restore") == 1
    assert events.count("microphone:restore") == 1


@pytest.mark.anyio
async def test_restore_failure_does_not_prevent_other_participant_restore() -> None:
    events: list[str] = []

    coordinator = PortAudioRefreshCoordinator(
        settle_seconds=0.0,
    )

    coordinator.register(
        FakeParticipant(
            "system",
            events,
            restore_error=OSError("system unavailable"),
        ),
    )
    coordinator.register(
        FakeParticipant("microphone", events),
    )

    coordinator.signal_refresh_requested()
    await coordinator.request_refresh()

    assert events == [
        "system:dispose",
        "microphone:dispose",
        "system:restore",
        "microphone:restore",
    ]


@pytest.mark.anyio
async def test_lookup_error_during_restore_does_not_fail_refresh() -> None:
    events: list[str] = []

    coordinator = PortAudioRefreshCoordinator(
        settle_seconds=0.0,
    )

    coordinator.register(
        FakeParticipant(
            "system",
            events,
            restore_error=LookupError("no default device"),
        ),
    )

    coordinator.signal_refresh_requested()
    await coordinator.request_refresh()

    assert events == [
        "system:dispose",
        "system:restore",
    ]


@pytest.mark.anyio
async def test_unexpected_restore_error_propagates() -> None:
    coordinator = PortAudioRefreshCoordinator(
        settle_seconds=0.0,
    )

    coordinator.register(
        FakeParticipant(
            "system",
            [],
            restore_error=RuntimeError("bug"),
        ),
    )

    with pytest.raises(
        RuntimeError,
        match="bug",
    ):
        coordinator.signal_refresh_requested()
        await coordinator.request_refresh()


@pytest.mark.anyio
async def test_teardown_attempts_every_participant_before_raising() -> None:
    events: list[str] = []

    class FailingParticipant:
        def __init__(self, name: str) -> None:
            self._name = name

        def prepare_for_portaudio_refresh(self) -> None:
            events.append(f"{self._name}:dispose")
            raise OSError(self._name)

        async def restore_after_portaudio_refresh(self) -> None:
            raise AssertionError("restore must not run")

    coordinator = PortAudioRefreshCoordinator(
        settle_seconds=0.0,
    )

    coordinator.register(
        FailingParticipant("system"),
    )
    coordinator.register(
        FailingParticipant("microphone"),
    )

    with pytest.raises(ExceptionGroup) as error:
        coordinator.signal_refresh_requested()
        await coordinator.request_refresh()

    assert events == [
        "system:dispose",
        "microphone:dispose",
    ]
    assert len(error.value.exceptions) == 2


@pytest.mark.anyio
async def test_signals_during_refresh_are_coalesced_without_another_request_task() -> None:
    # Arrange
    events: list[str] = []
    sleep = ControlledSleep()

    coordinator = PortAudioRefreshCoordinator(
        sleep=sleep,
        settle_seconds=0.5,
    )

    coordinator.register(
        FakeParticipant("system", events),
    )
    coordinator.register(
        FakeParticipant("microphone", events),
    )

    coordinator.signal_refresh_requested()

    refresh = asyncio.create_task(
        coordinator.request_refresh(),
    )

    await _wait_until(
        lambda: len(sleep.calls) == 1,
    )

    # Simulate several Core Audio callbacks while the capture lifecycle
    # that initiated the refresh is still awaiting the coordinator.
    coordinator.signal_refresh_requested()
    coordinator.signal_refresh_requested()
    coordinator.signal_refresh_requested()

    await sleep.release_next()

    # The generation changed during the quiet period, so the coordinator
    # must wait for another complete quiet period.
    await _wait_until(
        lambda: len(sleep.calls) == 2,
    )

    await sleep.release_next()

    await refresh

    # The capture's local event may still cause it to call request_refresh()
    # again after returning from the first await.
    await coordinator.request_refresh()

    # Assert
    assert events == [
        "system:dispose",
        "microphone:dispose",
        "system:restore",
        "microphone:restore",
    ]
