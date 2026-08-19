from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Protocol

from pycaw.callbacks import MMNotificationClient
from pycaw.pycaw import AudioUtilities

logger = logging.getLogger(__name__)


class _NotificationClient(MMNotificationClient):
    def __init__(
        self,
        on_change: Callable[[str | None], None],
    ) -> None:
        self._on_change = on_change

    def on_default_device_changed(
        self,
        flow: str,
        flow_id: int,
        role: str,
        role_id: int,
        default_device_id: str | None,
    ) -> None:
        del flow_id, role_id

        if flow != "eRender" or role != "eConsole":
            return

        logger.info(
            "default audio output changed endpoint_id=%r",
            default_device_id,
        )

        self._on_change(default_device_id)


class _EndpointNotificationEnumerator(Protocol):
    def RegisterEndpointNotificationCallback(
        self,
        client: object,
    ) -> None:
        ...

    def UnregisterEndpointNotificationCallback(
        self,
        client: object,
    ) -> None:
        ...


class WindowsAudioDeviceMonitor:
    """Observe Windows default render-device changes through Core Audio."""

    def __init__(self) -> None:
        self._enumerator: _EndpointNotificationEnumerator | None = None
        self._client: _NotificationClient | None = None
        self._handler: Callable[[str | None], None] | None = None
        self._started = False

    def set_change_handler(
        self,
        handler: Callable[[str | None], None],
    ) -> None:
        self._handler = handler

    def start(self) -> None:
        if self._started:
            return

        if self._handler is None:
            raise RuntimeError(
                "audio device change handler is not configured"
            )

        enumerator = self._create_enumerator()
        client = _NotificationClient(self._handler)

        enumerator.RegisterEndpointNotificationCallback(client)

        self._enumerator = enumerator
        self._client = client
        self._started = True

        logger.info("windows audio device monitor started")

    def stop(self) -> None:
        if not self._started:
            return

        enumerator = self._enumerator
        client = self._client

        if enumerator is not None and client is not None:
            enumerator.UnregisterEndpointNotificationCallback(client)

        self._enumerator = None
        self._client = None
        self._started = False

        logger.info("windows audio device monitor stopped")

    def _create_enumerator(self) -> _EndpointNotificationEnumerator:
        return AudioUtilities.GetDeviceEnumerator()