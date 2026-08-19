from __future__ import annotations

from typing import cast

import pytest

from app.audio.windows_device_monitor import WindowsAudioDeviceMonitor, _NotificationClient


class FakeEnumerator:
    def __init__(self) -> None:
        self.registered_client: object | None = None
        self.unregistered_client: object | None = None

    def RegisterEndpointNotificationCallback(
        self,
        client: object,
    ) -> None:
        self.registered_client = client

    def UnregisterEndpointNotificationCallback(
        self,
        client: object,
    ) -> None:
        self.unregistered_client = client


class FakeWindowsAudioDeviceMonitor(WindowsAudioDeviceMonitor):
    def __init__(
        self,
        enumerator: FakeEnumerator,
    ) -> None:
        super().__init__()
        self._test_enumerator = enumerator

    def _create_enumerator(self) -> FakeEnumerator:
        return self._test_enumerator


def create_monitor(
    enumerator: FakeEnumerator,
) -> WindowsAudioDeviceMonitor:
    return FakeWindowsAudioDeviceMonitor(enumerator)


def test_start_requires_change_handler() -> None:
    monitor = WindowsAudioDeviceMonitor()

    with pytest.raises(
        RuntimeError,
        match="change handler is not configured",
    ):
        monitor.start()


def test_start_registers_notification_client() -> None:
    enumerator = FakeEnumerator()
    monitor = create_monitor(enumerator)

    monitor.set_change_handler(lambda _: None)

    monitor.start()

    assert enumerator.registered_client is not None


def test_stop_unregisters_notification_client() -> None:
    enumerator = FakeEnumerator()
    monitor = create_monitor(enumerator)

    monitor.set_change_handler(lambda _: None)

    monitor.start()
    client = enumerator.registered_client

    monitor.stop()

    assert enumerator.unregistered_client is client


def test_start_is_idempotent() -> None:
    register_count = 0

    class CountingEnumerator(FakeEnumerator):
        def RegisterEndpointNotificationCallback(self, client: object) -> None:
            nonlocal register_count
            register_count += 1
            super().RegisterEndpointNotificationCallback(client)

    counting_enumerator = CountingEnumerator()
    monitor = create_monitor(counting_enumerator)

    monitor.set_change_handler(lambda _: None)

    monitor.start()
    monitor.start()

    assert register_count == 1


def test_stop_before_start_is_harmless() -> None:
    monitor = WindowsAudioDeviceMonitor()

    monitor.stop()


def test_stop_is_idempotent() -> None:
    unregister_count = 0

    class CountingEnumerator(FakeEnumerator):
        def UnregisterEndpointNotificationCallback(self, client: object) -> None:
            nonlocal unregister_count
            unregister_count += 1
            super().UnregisterEndpointNotificationCallback(client)

    enumerator = CountingEnumerator()
    monitor = create_monitor(enumerator)

    monitor.set_change_handler(lambda _: None)

    monitor.start()
    monitor.stop()
    monitor.stop()

    assert unregister_count == 1


def test_render_console_change_invokes_handler() -> None:
    enumerator = FakeEnumerator()
    received: list[str | None] = []

    monitor = create_monitor(enumerator)
    monitor.set_change_handler(received.append)
    monitor.start()

    client = enumerator.registered_client
    client = cast(
        _NotificationClient,
        enumerator.registered_client,
    )
    assert client is not None

    client.on_default_device_changed(
        "eRender",
        0,
        "eConsole",
        0,
        "endpoint-123",
    )

    assert received == ["endpoint-123"]


@pytest.mark.parametrize(
    ("flow", "role"),
    [
        ("eRender", "eMultimedia"),
        ("eRender", "eCommunications"),
        ("eCapture", "eConsole"),
        ("eCapture", "eMultimedia"),
        ("eCapture", "eCommunications"),
    ],
)
def test_non_console_render_changes_are_ignored(
    flow: str,
    role: str,
) -> None:
    enumerator = FakeEnumerator()
    received: list[str | None] = []

    monitor = create_monitor(enumerator)
    monitor.set_change_handler(received.append)
    monitor.start()

    client = enumerator.registered_client
    client = cast(
        _NotificationClient,
        enumerator.registered_client,
    )
    assert client is not None

    client.on_default_device_changed(
        flow,
        0,
        role,
        0,
        "endpoint-123",
    )

    assert received == []