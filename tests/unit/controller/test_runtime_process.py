from __future__ import annotations

from pathlib import Path

import pytest

from app.controller.runtime_process import (
    RuntimeFailedEvent,
    RuntimeGraphicsAdaptersObservedEvent,
    RuntimeProcessEvent,
    RuntimeProcessHost,
    RuntimeProcessSession,
    RuntimeProcessState,
    RuntimeStartedEvent,
    RuntimeTranscriptionObservedEvent,
)
from app.core.config.enums import (
    WhisperComputeType,
    WhisperDevice,
    WhisperRuntime,
)
from app.core.runtime_paths import RuntimePaths, create_development_runtime_paths
from app.observability.hardware import (
    GraphicsAdapterInfo,
    GraphicsAdaptersObservation,
)
from app.observability.transcription_runtime import (
    CTranslate2CapabilitiesObservation,
    TranscriptionRuntimeObservation,
)


class FakeRuntimeProcessSession:
    def __init__(
        self,
        pid: int,
    ) -> None:
        self._pid = pid
        self._exit_code: int | None = None
        self._alive = False
        self._events: list[RuntimeProcessEvent] = []

        self.start_calls = 0
        self.stop_calls = 0
        self.close_calls = 0

    @property
    def pid(self) -> int | None:
        return self._pid

    @property
    def exit_code(self) -> int | None:
        return self._exit_code

    def start(self) -> None:
        self.start_calls += 1
        self._alive = True

    def request_stop(self) -> None:
        self.stop_calls += 1

    def is_alive(self) -> bool:
        return self._alive

    def drain_events(self) -> tuple[RuntimeProcessEvent, ...]:
        events = tuple(self._events)
        self._events.clear()
        return events

    def wait(
        self,
        timeout_seconds: float | None = None,
    ) -> None:
        del timeout_seconds

    def close(self) -> None:
        self.close_calls += 1

    def publish(
        self,
        event: RuntimeProcessEvent,
    ) -> None:
        self._events.append(event)

    def exit(
        self,
        exit_code: int,
    ) -> None:
        self._exit_code = exit_code
        self._alive = False


class FakeRuntimeProcessSessionFactory:
    def __init__(self) -> None:
        self.sessions: list[FakeRuntimeProcessSession] = []

    def create(
        self,
        runtime_paths: RuntimePaths,
    ) -> RuntimeProcessSession:
        del runtime_paths

        session = FakeRuntimeProcessSession(
            pid=1000 + len(self.sessions),
        )

        self.sessions.append(session)

        return session


def create_host(
    tmp_path: Path,
) -> tuple[
    RuntimeProcessHost,
    FakeRuntimeProcessSessionFactory,
]:
    factory = FakeRuntimeProcessSessionFactory()

    host = RuntimeProcessHost(
        runtime_paths=create_development_runtime_paths(
            tmp_path,
        ),
        session_factory=factory,
    )

    return host, factory


def create_graphics_observation() -> GraphicsAdaptersObservation:
    return GraphicsAdaptersObservation.success(
        (
            GraphicsAdapterInfo(
                name="AMD Radeon RX 6800M",
                driver_version="32.0.21045.5002",
                pnp_device_id=("PCI\\VEN_1002&DEV_73DF"),
            ),
        )
    )


def create_transcription_runtime_observation() -> TranscriptionRuntimeObservation:
    return TranscriptionRuntimeObservation(
        runtime=WhisperRuntime.THEROCK,
        device=WhisperDevice.CUDA,
        configured_compute_type=(WhisperComputeType.FLOAT16),
        initialized=True,
        ctranslate2=(
            CTranslate2CapabilitiesObservation.success(
                cuda_device_count=1,
                supported_compute_types=(
                    "float16",
                    "float32",
                    "int8",
                ),
            )
        ),
    )


def test_initial_state_is_stopped(
    tmp_path: Path,
) -> None:
    host, _ = create_host(tmp_path)

    assert host.snapshot.state is RuntimeProcessState.STOPPED


def test_start_creates_fresh_runtime_in_starting_state(
    tmp_path: Path,
) -> None:
    host, factory = create_host(tmp_path)

    snapshot = host.start()

    assert snapshot.state is RuntimeProcessState.STARTING
    assert snapshot.pid == 1000
    assert len(factory.sessions) == 1
    assert factory.sessions[0].start_calls == 1


def test_started_event_transitions_to_running(
    tmp_path: Path,
) -> None:
    host, factory = create_host(tmp_path)

    host.start()

    factory.sessions[0].publish(
        RuntimeStartedEvent(),
    )

    snapshot = host.refresh()

    assert snapshot.state is RuntimeProcessState.RUNNING


def test_stop_requests_graceful_shutdown(
    tmp_path: Path,
) -> None:
    host, factory = create_host(tmp_path)

    host.start()
    factory.sessions[0].publish(
        RuntimeStartedEvent(),
    )
    host.refresh()

    snapshot = host.stop()

    assert snapshot.state is RuntimeProcessState.STOPPING
    assert factory.sessions[0].stop_calls == 1


def test_clean_exit_after_stop_transitions_to_stopped(
    tmp_path: Path,
) -> None:
    host, factory = create_host(tmp_path)

    host.start()
    factory.sessions[0].publish(
        RuntimeStartedEvent(),
    )
    host.refresh()
    host.stop()

    factory.sessions[0].exit(0)

    snapshot = host.refresh()

    assert snapshot.state is RuntimeProcessState.STOPPED
    assert snapshot.exit_code == 0
    assert factory.sessions[0].close_calls == 1


def test_unexpected_exit_transitions_to_failed(
    tmp_path: Path,
) -> None:
    host, factory = create_host(tmp_path)

    host.start()
    factory.sessions[0].publish(
        RuntimeStartedEvent(),
    )
    host.refresh()

    factory.sessions[0].exit(0)

    snapshot = host.refresh()

    assert snapshot.state is RuntimeProcessState.FAILED
    assert snapshot.failure_message is not None
    assert "unexpectedly" in snapshot.failure_message


def test_child_failure_is_preserved(
    tmp_path: Path,
) -> None:
    host, factory = create_host(tmp_path)

    host.start()

    factory.sessions[0].publish(
        RuntimeFailedEvent(
            message="RuntimeError: microphone unavailable",
        )
    )
    factory.sessions[0].exit(1)

    snapshot = host.refresh()

    assert snapshot.state is RuntimeProcessState.FAILED
    assert snapshot.failure_message == "RuntimeError: microphone unavailable"
    assert snapshot.exit_code == 1


def test_start_after_stop_creates_new_runtime(
    tmp_path: Path,
) -> None:
    host, factory = create_host(tmp_path)

    host.start()
    host.stop()

    factory.sessions[0].exit(0)
    host.refresh()

    host.start()

    assert len(factory.sessions) == 2
    assert factory.sessions[1] is not factory.sessions[0]


def test_start_while_runtime_is_active_is_rejected(
    tmp_path: Path,
) -> None:
    host, _ = create_host(tmp_path)

    host.start()

    with pytest.raises(
        RuntimeError,
        match="already active",
    ):
        host.start()


def test_repeated_stop_is_safe(
    tmp_path: Path,
) -> None:
    host, factory = create_host(tmp_path)

    host.start()

    host.stop()
    host.stop()

    assert factory.sessions[0].stop_calls == 1


def test_graphics_observation_is_stored_without_changing_state(
    tmp_path: Path,
) -> None:
    host, factory = create_host(tmp_path)

    host.start()

    session = factory.sessions[0]
    observation = create_graphics_observation()

    session.publish(
        RuntimeGraphicsAdaptersObservedEvent(
            observation=observation,
        )
    )

    snapshot = host.refresh()

    assert snapshot.state is RuntimeProcessState.STARTING

    assert host.diagnostics_snapshot.graphics_adapters == observation


def test_graphics_observation_remains_after_normal_stop(
    tmp_path: Path,
) -> None:
    host, factory = create_host(tmp_path)

    host.start()

    session = factory.sessions[0]
    observation = create_graphics_observation()

    session.publish(
        RuntimeGraphicsAdaptersObservedEvent(
            observation=observation,
        )
    )
    session.publish(
        RuntimeStartedEvent(),
    )

    host.refresh()

    assert host.snapshot.state is RuntimeProcessState.RUNNING

    host.stop()

    session.exit(0)

    snapshot = host.refresh()

    assert snapshot.state is RuntimeProcessState.STOPPED

    assert host.diagnostics_snapshot.graphics_adapters == observation


def test_fresh_start_clears_previous_graphics_observation(
    tmp_path: Path,
) -> None:
    host, factory = create_host(tmp_path)

    host.start()

    first_session = factory.sessions[0]
    observation = create_graphics_observation()

    first_session.publish(
        RuntimeGraphicsAdaptersObservedEvent(
            observation=observation,
        )
    )
    first_session.publish(
        RuntimeStartedEvent(),
    )

    host.refresh()

    host.stop()

    first_session.exit(0)

    host.refresh()

    assert host.diagnostics_snapshot.graphics_adapters == observation

    host.start()

    assert host.diagnostics_snapshot.graphics_adapters is None


def test_graphics_observation_remains_when_startup_fails(
    tmp_path: Path,
) -> None:
    host, factory = create_host(tmp_path)

    host.start()

    session = factory.sessions[0]
    observation = create_graphics_observation()

    session.publish(
        RuntimeGraphicsAdaptersObservedEvent(
            observation=observation,
        )
    )

    session.publish(
        RuntimeFailedEvent(
            message="runtime initialization failed",
        )
    )

    snapshot = host.refresh()

    assert snapshot.state is RuntimeProcessState.FAILED
    assert snapshot.failure_message == ("runtime initialization failed")

    assert host.diagnostics_snapshot.graphics_adapters == observation


def test_transcription_observation_is_stored_without_changing_state(
    tmp_path: Path,
) -> None:
    host, factory = create_host(tmp_path)

    host.start()

    session = factory.sessions[0]
    observation = create_transcription_runtime_observation()

    session.publish(
        RuntimeTranscriptionObservedEvent(
            observation=observation,
        )
    )

    snapshot = host.refresh()

    assert snapshot.state is RuntimeProcessState.STARTING

    assert host.diagnostics_snapshot.transcription_runtime == observation


def test_transcription_observation_remains_after_stop(
    tmp_path: Path,
) -> None:
    host, factory = create_host(tmp_path)

    host.start()

    session = factory.sessions[0]
    observation = create_transcription_runtime_observation()

    session.publish(
        RuntimeStartedEvent(),
    )

    session.publish(
        RuntimeTranscriptionObservedEvent(
            observation=observation,
        )
    )

    host.refresh()

    host.stop()
    session.exit(0)

    snapshot = host.refresh()

    assert snapshot.state is RuntimeProcessState.STOPPED

    assert host.diagnostics_snapshot.transcription_runtime == observation


def test_fresh_start_clears_transcription_observation(
    tmp_path: Path,
) -> None:
    host, factory = create_host(tmp_path)

    host.start()

    first_session = factory.sessions[0]

    first_session.publish(
        RuntimeStartedEvent(),
    )

    first_session.publish(
        RuntimeTranscriptionObservedEvent(
            observation=(create_transcription_runtime_observation()),
        )
    )

    host.refresh()

    host.stop()
    first_session.exit(0)
    host.refresh()

    assert host.diagnostics_snapshot.transcription_runtime is not None

    host.start()

    assert host.diagnostics_snapshot.transcription_runtime is None
