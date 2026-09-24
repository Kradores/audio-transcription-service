from pathlib import Path

import pytest

from app.controller.window import ControllerWindow
from app.core.config.enums import WhisperModel
from app.models.whisper import (
    WhisperModelProvisioningState,
    WhisperModelStatus,
)


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        (
            WhisperModelProvisioningState.READY,
            "medium — Ready",
        ),
        (
            WhisperModelProvisioningState.NOT_INSTALLED,
            "medium — Not installed",
        ),
        (
            WhisperModelProvisioningState.DOWNLOADING,
            "medium — Downloading",
        ),
        (
            WhisperModelProvisioningState.FAILED,
            "medium — Failed",
        ),
    ],
)
def test_model_status_text(
    state: WhisperModelProvisioningState,
    expected: str,
) -> None:
    status = WhisperModelStatus(
        model=WhisperModel.MEDIUM,
        path=Path("models") / "medium",
        state=state,
    )

    assert ControllerWindow._model_status_text(status) == expected


@pytest.mark.parametrize(
    ("state", "expected_text", "expected_available"),
    [
        (
            WhisperModelProvisioningState.READY,
            "Model Installed",
            False,
        ),
        (
            WhisperModelProvisioningState.NOT_INSTALLED,
            "Install Model",
            True,
        ),
        (
            WhisperModelProvisioningState.DOWNLOADING,
            "Installing Model...",
            False,
        ),
        (
            WhisperModelProvisioningState.FAILED,
            "Retry Model Install",
            True,
        ),
    ],
)
def test_model_action(
    state: WhisperModelProvisioningState,
    expected_text: str,
    expected_available: bool,
) -> None:
    status = WhisperModelStatus(
        model=WhisperModel.MEDIUM,
        path=Path("models") / "medium",
        state=state,
    )

    assert ControllerWindow._model_action(status) == (
        expected_text,
        expected_available,
    )
