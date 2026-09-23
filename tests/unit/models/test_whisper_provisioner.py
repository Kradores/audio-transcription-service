from pathlib import Path

import pytest

from app.core.config.enums import WhisperModel
from app.models.whisper import (
    WHISPER_MODEL_READY_MARKER_NAME,
    LocalWhisperModelResolver,
)
from app.models.whisper_provisioner import (
    WHISPER_MODEL_REPOSITORIES,
    HuggingFaceWhisperModelProvisioner,
    WhisperModelProvisioningError,
)


def _write_valid_model(
    directory: Path,
) -> None:
    directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    (directory / "config.json").touch()
    (directory / "model.bin").touch()
    (directory / "tokenizer.json").touch()


def test_provision_downloads_model_into_temporary_directory(
    tmp_path: Path,
) -> None:
    models_directory = tmp_path / "models"
    resolver = LocalWhisperModelResolver(models_directory)

    downloads: list[tuple[str, Path]] = []

    def download(
        repository_id: str,
        destination: Path,
    ) -> None:
        downloads.append((repository_id, destination))
        _write_valid_model(destination)

    provisioner = HuggingFaceWhisperModelProvisioner(
        resolver=resolver,
        downloader=download,
    )

    provisioner.provision(WhisperModel.SMALL)

    assert downloads == [
        (
            WHISPER_MODEL_REPOSITORIES[WhisperModel.SMALL],
            models_directory / ".small.download",
        )
    ]


def test_provision_publishes_ready_model(
    tmp_path: Path,
) -> None:
    models_directory = tmp_path / "models"
    resolver = LocalWhisperModelResolver(models_directory)

    def download(
        repository_id: str,
        destination: Path,
    ) -> None:
        del repository_id
        _write_valid_model(destination)

    provisioner = HuggingFaceWhisperModelProvisioner(
        resolver=resolver,
        downloader=download,
    )

    result = provisioner.provision(WhisperModel.SMALL)

    assert result.ready is True
    assert result.path == models_directory / "small"
    assert (result.path / WHISPER_MODEL_READY_MARKER_NAME).is_file()


def test_provision_does_not_download_existing_ready_model(
    tmp_path: Path,
) -> None:
    models_directory = tmp_path / "models"
    model_directory = models_directory / "small"

    _write_valid_model(model_directory)
    (model_directory / WHISPER_MODEL_READY_MARKER_NAME).touch()

    resolver = LocalWhisperModelResolver(models_directory)

    def download(
        repository_id: str,
        destination: Path,
    ) -> None:
        raise AssertionError("ready model must not be downloaded")

    provisioner = HuggingFaceWhisperModelProvisioner(
        resolver=resolver,
        downloader=download,
    )

    result = provisioner.provision(WhisperModel.SMALL)

    assert result.ready is True


def test_provision_does_not_publish_incomplete_model(
    tmp_path: Path,
) -> None:
    models_directory = tmp_path / "models"
    resolver = LocalWhisperModelResolver(models_directory)

    def download(
        repository_id: str,
        destination: Path,
    ) -> None:
        del repository_id

        destination.mkdir(
            parents=True,
            exist_ok=True,
        )
        (destination / "config.json").touch()

    provisioner = HuggingFaceWhisperModelProvisioner(
        resolver=resolver,
        downloader=download,
    )

    with pytest.raises(
        WhisperModelProvisioningError,
        match="incomplete",
    ):
        provisioner.provision(WhisperModel.SMALL)

    result = resolver.resolve(WhisperModel.SMALL)

    assert result.ready is False
    assert (models_directory / "small").exists() is False


def test_failed_download_does_not_replace_existing_model(
    tmp_path: Path,
) -> None:
    models_directory = tmp_path / "models"
    existing_directory = models_directory / "small"

    existing_directory.mkdir(
        parents=True,
        exist_ok=True,
    )
    existing_file = existing_directory / "existing.txt"
    existing_file.write_text(
        "existing",
        encoding="utf-8",
    )

    resolver = LocalWhisperModelResolver(models_directory)

    def download(
        repository_id: str,
        destination: Path,
    ) -> None:
        del repository_id
        del destination

        raise ConnectionError("download failed")

    provisioner = HuggingFaceWhisperModelProvisioner(
        resolver=resolver,
        downloader=download,
    )

    with pytest.raises(
        ConnectionError,
        match="download failed",
    ):
        provisioner.provision(WhisperModel.SMALL)

    assert existing_file.read_text(encoding="utf-8") == "existing"
