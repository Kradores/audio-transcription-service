from pathlib import Path

from app.controller.model_status import (
    ConfiguredWhisperModelStatusProvider,
)
from app.core.config.enums import WhisperModel
from app.core.config.models import Settings
from app.models.whisper import (
    WHISPER_MODEL_READY_MARKER_NAME,
    LocalWhisperModelResolver,
    WhisperModelProvisioningState,
)
from tests.unit.core.config.builders import SettingsBuilder


def test_status_reports_configured_model_not_installed(
    tmp_path: Path,
) -> None:
    settings = SettingsBuilder().with_whisper_model("medium").build()

    provider = ConfiguredWhisperModelStatusProvider(
        settings_loader=lambda: settings,
        resolver=LocalWhisperModelResolver(tmp_path / "models"),
    )

    status = provider.get_status()

    assert status.model is WhisperModel.MEDIUM
    assert status.path == tmp_path / "models" / "medium"
    assert status.state is WhisperModelProvisioningState.NOT_INSTALLED
    assert status.failure_message is None


def test_status_reports_configured_model_ready(
    tmp_path: Path,
) -> None:
    models_directory = tmp_path / "models"
    model_directory = models_directory / "medium"

    model_directory.mkdir(parents=True)

    (model_directory / WHISPER_MODEL_READY_MARKER_NAME).touch()

    settings = SettingsBuilder().with_whisper_model("medium").build()

    provider = ConfiguredWhisperModelStatusProvider(
        settings_loader=lambda: settings,
        resolver=LocalWhisperModelResolver(models_directory),
    )

    status = provider.get_status()

    assert status.model is WhisperModel.MEDIUM
    assert status.path == model_directory
    assert status.state is WhisperModelProvisioningState.READY


def test_status_reloads_configuration_for_each_query(
    tmp_path: Path,
) -> None:
    settings = [
        SettingsBuilder().with_whisper_model("small").build(),
        SettingsBuilder().with_whisper_model("medium").build(),
    ]

    call_count = 0

    def load_settings() -> Settings:
        nonlocal call_count

        result = settings[call_count]
        call_count += 1

        return result

    provider = ConfiguredWhisperModelStatusProvider(
        settings_loader=load_settings,
        resolver=LocalWhisperModelResolver(tmp_path / "models"),
    )

    first = provider.get_status()
    second = provider.get_status()

    assert first.model is WhisperModel.SMALL
    assert second.model is WhisperModel.MEDIUM
