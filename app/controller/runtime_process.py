from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from app.core.runtime_paths import RuntimePaths
from app.observability.hardware import (
    GraphicsAdaptersObservation,
)
from app.observability.transcription_runtime import TranscriptionRuntimeObservation

logger = logging.getLogger(__name__)


class RuntimeProcessState(StrEnum):
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class RuntimeStartedEvent:
    """Runtime application startup completed successfully."""


@dataclass(frozen=True, slots=True)
class RuntimeFailedEvent:
    """Runtime process failed."""

    message: str


type RuntimeProcessEvent = (
    RuntimeStartedEvent
    | RuntimeFailedEvent
    | RuntimeGraphicsAdaptersObservedEvent
    | RuntimeTranscriptionObservedEvent
)


@dataclass(frozen=True, slots=True)
class RuntimeProcessSnapshot:
    state: RuntimeProcessState
    pid: int | None
    exit_code: int | None
    failure_message: str | None


@dataclass(frozen=True, slots=True)
class RuntimeGraphicsAdaptersObservedEvent:
    """Windows graphics-adapter observation from the runtime child."""

    observation: GraphicsAdaptersObservation


@dataclass(frozen=True, slots=True)
class RuntimeProcessDiagnosticsSnapshot:
    graphics_adapters: GraphicsAdaptersObservation | None
    transcription_runtime: TranscriptionRuntimeObservation | None


@dataclass(frozen=True, slots=True)
class RuntimeTranscriptionObservedEvent:
    """Transcription runtime observation from the child."""

    observation: TranscriptionRuntimeObservation


class RuntimeProcessSession(Protocol):
    @property
    def pid(self) -> int | None:
        """Return the child process ID when started."""

    @property
    def exit_code(self) -> int | None:
        """Return the child exit code when available."""

    def start(self) -> None:
        """Start the runtime child process."""

    def request_stop(self) -> None:
        """Request graceful runtime shutdown."""

    def is_alive(self) -> bool:
        """Return whether the child process is alive."""

    def drain_events(self) -> tuple[RuntimeProcessEvent, ...]:
        """Return currently available runtime lifecycle events."""

    def wait(
        self,
        timeout_seconds: float | None = None,
    ) -> None:
        """Wait for the runtime process."""

    def close(self) -> None:
        """Release process-control resources."""


class RuntimeProcessSessionFactory(Protocol):
    def create(
        self,
        runtime_paths: RuntimePaths,
    ) -> RuntimeProcessSession:
        """Create one fresh runtime-process session."""


class RuntimeProcessHost:
    """Own controller-side state for one runtime process at a time."""

    def __init__(
        self,
        *,
        runtime_paths: RuntimePaths,
        session_factory: RuntimeProcessSessionFactory,
    ) -> None:
        self._runtime_paths = runtime_paths
        self._session_factory = session_factory

        self._session: RuntimeProcessSession | None = None
        self._state = RuntimeProcessState.STOPPED

        self._pid: int | None = None
        self._exit_code: int | None = None
        self._failure_message: str | None = None
        self._stop_requested = False

        self._graphics_adapters: GraphicsAdaptersObservation | None = None
        self._transcription_runtime: TranscriptionRuntimeObservation | None = None

    @property
    def snapshot(self) -> RuntimeProcessSnapshot:
        return RuntimeProcessSnapshot(
            state=self._state,
            pid=self._pid,
            exit_code=self._exit_code,
            failure_message=self._failure_message,
        )

    @property
    def diagnostics_snapshot(
        self,
    ) -> RuntimeProcessDiagnosticsSnapshot:
        return RuntimeProcessDiagnosticsSnapshot(
            graphics_adapters=self._graphics_adapters,
            transcription_runtime=self._transcription_runtime,
        )

    def start(self) -> RuntimeProcessSnapshot:
        """Start a fresh runtime process."""

        self.refresh()

        if self._session is not None and self._session.is_alive():
            raise RuntimeError(
                "runtime process is already active",
            )

        self._state = RuntimeProcessState.STARTING
        self._pid = None
        self._exit_code = None
        self._failure_message = None
        self._stop_requested = False

        self._graphics_adapters = None
        self._transcription_runtime = None

        try:
            session = self._session_factory.create(
                self._runtime_paths,
            )
            self._session = session

            session.start()
            self._pid = session.pid

        except Exception as exc:
            self._state = RuntimeProcessState.FAILED
            self._failure_message = self._format_exception(exc)
            self._release_session()

        return self.snapshot

    def stop(self) -> RuntimeProcessSnapshot:
        """Request graceful shutdown of the active runtime."""

        self.refresh()

        session = self._session

        if session is None or not session.is_alive():
            return self.snapshot

        if self._state is RuntimeProcessState.STOPPING:
            return self.snapshot

        if self._state not in {
            RuntimeProcessState.STARTING,
            RuntimeProcessState.RUNNING,
        }:
            return self.snapshot

        self._stop_requested = True
        self._state = RuntimeProcessState.STOPPING

        try:
            session.request_stop()
        except Exception as exc:
            self._state = RuntimeProcessState.FAILED
            self._failure_message = self._format_exception(exc)

        return self.snapshot

    def refresh(self) -> RuntimeProcessSnapshot:
        """Refresh controller state from child events and process state."""

        session = self._session

        if session is None:
            return self.snapshot

        for event in session.drain_events():
            self._apply_event(event)

        if session.is_alive():
            return self.snapshot

        session.wait(timeout_seconds=0.0)

        self._exit_code = session.exit_code

        previous_state = self._state

        if (
            previous_state is RuntimeProcessState.STOPPING
            and self._stop_requested
            and self._exit_code == 0
        ):
            self._state = RuntimeProcessState.STOPPED
            self._failure_message = None

        elif previous_state is not RuntimeProcessState.FAILED:
            self._state = RuntimeProcessState.FAILED
            self._failure_message = self._unexpected_exit_message(
                previous_state,
                self._exit_code,
            )

        elif self._failure_message is None:
            self._failure_message = self._unexpected_exit_message(
                previous_state,
                self._exit_code,
            )

        self._release_session()

        return self.snapshot

    def _apply_event(
        self,
        event: RuntimeProcessEvent,
    ) -> None:
        if isinstance(
            event,
            RuntimeGraphicsAdaptersObservedEvent,
        ):
            self._graphics_adapters = event.observation
            return

        if isinstance(
            event,
            RuntimeTranscriptionObservedEvent,
        ):
            self._transcription_runtime = event.observation
            return

        if isinstance(event, RuntimeStartedEvent):
            if self._state is RuntimeProcessState.STARTING:
                self._state = RuntimeProcessState.RUNNING

            return

        self._state = RuntimeProcessState.FAILED
        self._failure_message = event.message

    def _release_session(self) -> None:
        session = self._session

        if session is None:
            return

        try:
            session.close()
        except Exception:
            logger.exception(
                "failed to release runtime process resources",
            )
        finally:
            self._session = None

    @staticmethod
    def _format_exception(
        exc: Exception,
    ) -> str:
        message = str(exc).strip()

        if not message:
            return type(exc).__name__

        return f"{type(exc).__name__}: {message}"

    @staticmethod
    def _unexpected_exit_message(
        previous_state: RuntimeProcessState,
        exit_code: int | None,
    ) -> str:
        if previous_state is RuntimeProcessState.STARTING:
            return f"Runtime process exited before reporting readiness (exit_code={exit_code})."

        if previous_state is RuntimeProcessState.STOPPING:
            return f"Runtime process failed during graceful shutdown (exit_code={exit_code})."

        return f"Runtime process exited unexpectedly (exit_code={exit_code})."
