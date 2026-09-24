from __future__ import annotations

import logging
import queue
import threading
from dataclasses import dataclass

from app.controller.model_status import (
    WhisperModelStatusProvider,
)
from app.core.config.enums import WhisperModel
from app.models.whisper import (
    ResolvedWhisperModel,
    WhisperModelProvisioningState,
    WhisperModelStatus,
)
from app.models.whisper_provisioner import (
    WhisperModelProvisioner,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class _ProvisioningSucceeded:
    model: WhisperModel
    resolved: ResolvedWhisperModel


@dataclass(frozen=True, slots=True)
class _ProvisioningFailed:
    model: WhisperModel
    message: str


type _ProvisioningEvent = _ProvisioningSucceeded | _ProvisioningFailed


class WhisperModelProvisioningHost:
    """Own controller-side model provisioning state."""

    def __init__(
        self,
        *,
        status_provider: WhisperModelStatusProvider,
        provisioner: WhisperModelProvisioner,
    ) -> None:
        self._status_provider = status_provider
        self._provisioner = provisioner

        self._status = status_provider.get_status()

        self._events: queue.SimpleQueue[_ProvisioningEvent] = queue.SimpleQueue()

        self._worker: threading.Thread | None = None

    @property
    def status(self) -> WhisperModelStatus:
        return self._status

    def refresh(self) -> WhisperModelStatus:
        """Apply provisioning-worker events without reloading configuration."""

        self._apply_worker_events()

        worker = self._worker

        if worker is not None and not worker.is_alive():
            worker.join()
            self._worker = None

            # The worker may have published its event immediately
            # before terminating.
            self._apply_worker_events()

        return self._status

    def reload_configured_status(
        self,
    ) -> WhisperModelStatus:
        """Reload the configured model and its persisted local state."""

        self.refresh()

        if self._worker is not None:
            return self._status

        self._status = self._status_provider.get_status()
        return self._status

    def provision(self) -> WhisperModelStatus:
        self.refresh()

        if self._status.state is WhisperModelProvisioningState.DOWNLOADING:
            return self._status

        target = self.reload_configured_status()

        if target.state is WhisperModelProvisioningState.READY:
            return target

        self._status = WhisperModelStatus(
            model=target.model,
            path=target.path,
            state=WhisperModelProvisioningState.DOWNLOADING,
        )

        logger.info(
            "Whisper model provisioning started model=%s path=%s",
            target.model.value,
            target.path,
        )

        worker = threading.Thread(
            target=self._run_provisioning,
            args=(target.model,),
            name=f"whisper-model-{target.model.value}",
            daemon=True,
        )

        self._worker = worker
        worker.start()

        return self._status

    def _run_provisioning(
        self,
        model: WhisperModel,
    ) -> None:
        try:
            resolved = self._provisioner.provision(model)
        except Exception as exc:
            logger.exception(
                "Whisper model provisioning failed model=%s",
                model.value,
            )

            self._events.put(
                _ProvisioningFailed(
                    model=model,
                    message=self._format_exception(exc),
                )
            )
            return

        self._events.put(
            _ProvisioningSucceeded(
                model=model,
                resolved=resolved,
            )
        )

    def _apply_worker_events(self) -> None:
        while True:
            try:
                event = self._events.get_nowait()
            except queue.Empty:
                return

            if isinstance(
                event,
                _ProvisioningSucceeded,
            ):
                self._status = WhisperModelStatus(
                    model=event.model,
                    path=event.resolved.path,
                    state=WhisperModelProvisioningState.READY,
                )

                logger.info(
                    "Whisper model provisioning completed model=%s path=%s",
                    event.model.value,
                    event.resolved.path,
                )

                continue

            self._status = WhisperModelStatus(
                model=event.model,
                path=self._status.path,
                state=(WhisperModelProvisioningState.FAILED),
                failure_message=event.message,
            )

    @staticmethod
    def _format_exception(
        exc: Exception,
    ) -> str:
        message = str(exc).strip()

        if not message:
            return type(exc).__name__

        return f"{type(exc).__name__}: {message}"
