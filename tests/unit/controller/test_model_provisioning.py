from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

import pytest

from app.controller.model_provisioning import (
    WhisperModelProvisioningHost,
)
from app.controller.model_status import (
    ConfiguredWhisperModelStatusProvider,
)
from app.core.config.enums import WhisperModel
from app.models.whisper import (
    WHISPER_MODEL_READY_MARKER_NAME,
    LocalWhisperModelResolver,
    ResolvedWhisperModel,
    WhisperModelProvisioningState,
    WhisperModelStatus,
)
from tests.unit.core.config.builders import SettingsBuilder


class BlockingProvisioner:
    def __init__(
        self,
        *,
        result: ResolvedWhisperModel,
    ) -> None:
        self._result = result
        self.started = threading.Event()
        self.release = threading.Event()
        self.calls: list[WhisperModel] = []

    def provision(
        self,
        model: WhisperModel,
    ) -> ResolvedWhisperModel:
        self.calls.append(model)
        self.started.set()

        assert self.release.wait(timeout=5.0)

        return self._result


class ControlledProvisioner:
    def __init__(
        self,
        *,
        result: ResolvedWhisperModel | None = None,
        error: Exception | None = None,
    ) -> None:
        self._result = result
        self._error = error

        self.started = threading.Event()
        self.release = threading.Event()

        self.calls: list[WhisperModel] = []

    def provision(
        self,
        model: WhisperModel,
    ) -> ResolvedWhisperModel:
        self.calls.append(model)
        self.started.set()

        if not self.release.wait(timeout=5.0):
            raise TimeoutError("test did not release provisioning worker")

        if self._error is not None:
            raise self._error

        if self._result is None:
            raise AssertionError("successful provisioning requires a result")

        if not self._result.ready:
            raise AssertionError("successful provisioning must return a ready model")

        self._result.path.mkdir(
            parents=True,
            exist_ok=True,
        )

        (self._result.path / WHISPER_MODEL_READY_MARKER_NAME).touch()

        return self._result


class CountingStatusProvider:
    def __init__(
        self,
        status: WhisperModelStatus,
    ) -> None:
        self.status = status
        self.calls = 0

    def get_status(self) -> WhisperModelStatus:
        self.calls += 1
        return self.status


def _create_host(
    tmp_path: Path,
    provisioner: ControlledProvisioner,
    *,
    ready: bool = False,
) -> WhisperModelProvisioningHost:
    models_directory = tmp_path / "models"
    model_directory = models_directory / "medium"

    if ready:
        model_directory.mkdir(
            parents=True,
            exist_ok=True,
        )
        (model_directory / WHISPER_MODEL_READY_MARKER_NAME).touch()

    settings = SettingsBuilder().with_whisper_model("medium").build()

    status_provider = ConfiguredWhisperModelStatusProvider(
        settings_loader=lambda: settings,
        resolver=LocalWhisperModelResolver(models_directory),
    )

    return WhisperModelProvisioningHost(
        status_provider=status_provider,
        provisioner=provisioner,
    )


def _wait_for_state(
    host: WhisperModelProvisioningHost,
    expected: WhisperModelProvisioningState,
    *,
    timeout_seconds: float = 2.0,
) -> WhisperModelStatus:
    deadline = time.monotonic() + timeout_seconds

    while time.monotonic() < deadline:
        status = host.refresh()

        if status.state is expected:
            return status

        time.sleep(0.001)

    pytest.fail(
        "timed out waiting for model provisioning state "
        f"{expected.value!r}; current state="
        f"{host.status.state.value!r}"
    )


def test_not_installed_model_transitions_to_downloading(
    tmp_path: Path,
) -> None:
    model_path = tmp_path / "models" / "medium"

    provisioner = ControlledProvisioner(
        result=ResolvedWhisperModel(
            model=WhisperModel.MEDIUM,
            path=model_path,
            ready=True,
        ),
    )

    host = _create_host(
        tmp_path,
        provisioner,
    )

    status = host.provision()

    try:
        assert status.state is WhisperModelProvisioningState.DOWNLOADING
        assert status.model is WhisperModel.MEDIUM
        assert status.path == model_path
        assert provisioner.started.wait(timeout=2.0)
        assert provisioner.calls == [WhisperModel.MEDIUM]
    finally:
        provisioner.release.set()


def test_second_provision_while_downloading_does_not_start_second_worker(
    tmp_path: Path,
) -> None:
    model_path = tmp_path / "models" / "medium"

    provisioner = ControlledProvisioner(
        result=ResolvedWhisperModel(
            model=WhisperModel.MEDIUM,
            path=model_path,
            ready=True,
        ),
    )

    host = _create_host(
        tmp_path,
        provisioner,
    )

    first = host.provision()

    assert provisioner.started.wait(timeout=2.0)

    second = host.provision()

    try:
        assert first.state is WhisperModelProvisioningState.DOWNLOADING
        assert second.state is WhisperModelProvisioningState.DOWNLOADING
        assert provisioner.calls == [WhisperModel.MEDIUM]
    finally:
        provisioner.release.set()


def test_successful_provisioning_transitions_to_ready(
    tmp_path: Path,
) -> None:
    model_path = tmp_path / "models" / "medium"

    provisioner = ControlledProvisioner(
        result=ResolvedWhisperModel(
            model=WhisperModel.MEDIUM,
            path=model_path,
            ready=True,
        ),
    )

    host = _create_host(
        tmp_path,
        provisioner,
    )

    initial = host.provision()

    assert initial.state is WhisperModelProvisioningState.DOWNLOADING
    assert provisioner.started.wait(timeout=2.0)

    provisioner.release.set()

    status = _wait_for_state(
        host,
        WhisperModelProvisioningState.READY,
    )

    assert status.model is WhisperModel.MEDIUM
    assert status.path == model_path
    assert status.failure_message is None
    assert provisioner.calls == [WhisperModel.MEDIUM]


def test_failed_provisioning_transitions_to_failed_with_message(
    tmp_path: Path,
) -> None:
    provisioner = ControlledProvisioner(
        error=RuntimeError("download failed"),
    )

    host = _create_host(
        tmp_path,
        provisioner,
    )

    initial = host.provision()

    assert initial.state is WhisperModelProvisioningState.DOWNLOADING
    assert provisioner.started.wait(timeout=2.0)

    provisioner.release.set()

    status = _wait_for_state(
        host,
        WhisperModelProvisioningState.FAILED,
    )

    assert status.model is WhisperModel.MEDIUM
    assert status.failure_message == ("RuntimeError: download failed")
    assert provisioner.calls == [WhisperModel.MEDIUM]


def test_ready_model_does_not_start_provisioning_worker(
    tmp_path: Path,
) -> None:
    model_path = tmp_path / "models" / "medium"

    provisioner = ControlledProvisioner(
        result=ResolvedWhisperModel(
            model=WhisperModel.MEDIUM,
            path=model_path,
            ready=True,
        ),
    )

    host = _create_host(
        tmp_path,
        provisioner,
        ready=True,
    )

    status = host.provision()

    assert status.state is WhisperModelProvisioningState.READY
    assert status.model is WhisperModel.MEDIUM
    assert status.path == model_path

    assert provisioner.calls == []
    assert not provisioner.started.is_set()


def test_provision_does_not_start_second_download(
    tmp_path: Path,
) -> None:
    settings = SettingsBuilder().with_whisper_model("medium").build()

    model_path = tmp_path / "models" / "medium"

    status_provider = ConfiguredWhisperModelStatusProvider(
        settings_loader=lambda: settings,
        resolver=LocalWhisperModelResolver(tmp_path / "models"),
    )

    provisioner = BlockingProvisioner(
        result=ResolvedWhisperModel(
            model=WhisperModel.MEDIUM,
            path=model_path,
            ready=True,
        )
    )

    host = WhisperModelProvisioningHost(
        status_provider=status_provider,
        provisioner=provisioner,
    )

    first = host.provision()

    assert provisioner.started.wait(timeout=5.0)

    second = host.provision()

    assert first.state is WhisperModelProvisioningState.DOWNLOADING
    assert second.state is WhisperModelProvisioningState.DOWNLOADING
    assert provisioner.calls == [WhisperModel.MEDIUM]

    provisioner.release.set()


def test_refresh_does_not_reload_configured_status(
    tmp_path: Path,
) -> None:
    status_provider = CountingStatusProvider(
        WhisperModelStatus(
            model=WhisperModel.MEDIUM,
            path=tmp_path / "models" / "medium",
            state=(WhisperModelProvisioningState.NOT_INSTALLED),
        )
    )

    provisioner = ControlledProvisioner()

    host = WhisperModelProvisioningHost(
        status_provider=status_provider,
        provisioner=provisioner,
    )

    assert status_provider.calls == 1

    host.refresh()
    host.refresh()
    host.refresh()

    assert status_provider.calls == 1


def test_reload_configured_status_queries_provider(
    tmp_path: Path,
) -> None:
    initial = WhisperModelStatus(
        model=WhisperModel.SMALL,
        path=tmp_path / "models" / "small",
        state=WhisperModelProvisioningState.NOT_INSTALLED,
    )

    updated = WhisperModelStatus(
        model=WhisperModel.MEDIUM,
        path=tmp_path / "models" / "medium",
        state=WhisperModelProvisioningState.READY,
    )

    status_provider = CountingStatusProvider(initial)

    host = WhisperModelProvisioningHost(
        status_provider=status_provider,
        provisioner=ControlledProvisioner(),
    )

    status_provider.status = updated

    result = host.reload_configured_status()

    assert result == updated
    assert status_provider.calls == 2


def test_successful_provisioning_logs_lifecycle(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    model_path = tmp_path / "models" / "medium"

    provisioner = ControlledProvisioner(
        result=ResolvedWhisperModel(
            model=WhisperModel.MEDIUM,
            path=model_path,
            ready=True,
        ),
    )

    host = _create_host(
        tmp_path,
        provisioner,
    )

    with caplog.at_level(
        logging.INFO,
        logger="app.controller.model_provisioning",
    ):
        host.provision()

        assert provisioner.started.wait(timeout=2.0)

        provisioner.release.set()

        _wait_for_state(
            host,
            WhisperModelProvisioningState.READY,
        )

    messages = [record.getMessage() for record in caplog.records]

    assert f"Whisper model provisioning started model=medium path={model_path}" in messages

    assert f"Whisper model provisioning completed model=medium path={model_path}" in messages


def test_failed_provisioning_logs_failure(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    provisioner = ControlledProvisioner(
        error=RuntimeError("download failed"),
    )

    host = _create_host(
        tmp_path,
        provisioner,
    )

    with caplog.at_level(
        logging.ERROR,
        logger="app.controller.model_provisioning",
    ):
        host.provision()

        assert provisioner.started.wait(timeout=2.0)

        provisioner.release.set()

        _wait_for_state(
            host,
            WhisperModelProvisioningState.FAILED,
        )

    messages = [record.getMessage() for record in caplog.records]

    assert "Whisper model provisioning failed model=medium" in messages
