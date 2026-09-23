from pathlib import Path

import pytest

from app.core.config.enums import WhisperModel
from app.models.whisper import (
    WHISPER_MODEL_READY_MARKER_NAME,
    LocalWhisperModelResolver,
    WhisperModelNotReadyError,
    resolve_ready_whisper_model,
)


@pytest.mark.parametrize(
    ("model", "directory_name"),
    [
        (WhisperModel.TINY, "tiny"),
        (WhisperModel.BASE, "base"),
        (WhisperModel.SMALL, "small"),
        (WhisperModel.MEDIUM, "medium"),
        (WhisperModel.LARGE, "large-v3"),
        (WhisperModel.TURBO, "turbo"),
    ],
)
def test_resolve_maps_model_to_application_owned_directory(
    tmp_path: Path,
    model: WhisperModel,
    directory_name: str,
) -> None:
    # Arrange
    models_directory = tmp_path / "models"
    resolver = LocalWhisperModelResolver(models_directory)

    # Act
    result = resolver.resolve(model)

    # Assert
    assert result.model is model
    assert result.path == models_directory / directory_name


def test_resolve_reports_model_not_ready_when_directory_does_not_exist(
    tmp_path: Path,
) -> None:
    # Arrange
    resolver = LocalWhisperModelResolver(tmp_path / "models")

    # Act
    result = resolver.resolve(WhisperModel.SMALL)

    # Assert
    assert result.ready is False


def test_resolve_reports_model_not_ready_without_ready_marker(
    tmp_path: Path,
) -> None:
    # Arrange
    model_directory = tmp_path / "models" / "small"
    model_directory.mkdir(parents=True)

    resolver = LocalWhisperModelResolver(tmp_path / "models")

    # Act
    result = resolver.resolve(WhisperModel.SMALL)

    # Assert
    assert result.ready is False


def test_resolve_reports_model_ready_when_ready_marker_exists(
    tmp_path: Path,
) -> None:
    # Arrange
    model_directory = tmp_path / "models" / "small"
    model_directory.mkdir(parents=True)

    (model_directory / WHISPER_MODEL_READY_MARKER_NAME).touch()

    resolver = LocalWhisperModelResolver(tmp_path / "models")

    # Act
    result = resolver.resolve(WhisperModel.SMALL)

    # Assert
    assert result.ready is True


def test_resolve_does_not_create_model_storage(
    tmp_path: Path,
) -> None:
    # Arrange
    models_directory = tmp_path / "models"
    resolver = LocalWhisperModelResolver(models_directory)

    # Act
    resolver.resolve(WhisperModel.SMALL)

    # Assert
    assert models_directory.exists() is False


def test_resolve_ready_whisper_model_returns_ready_model(
    tmp_path: Path,
) -> None:
    models_directory = tmp_path / "models"
    model_directory = models_directory / "small"
    model_directory.mkdir(parents=True)

    (model_directory / WHISPER_MODEL_READY_MARKER_NAME).touch()

    resolver = LocalWhisperModelResolver(models_directory)

    result = resolve_ready_whisper_model(
        resolver,
        WhisperModel.SMALL,
    )

    assert result.path == model_directory
    assert result.ready is True


def test_resolve_ready_whisper_model_rejects_missing_model(
    tmp_path: Path,
) -> None:
    resolver = LocalWhisperModelResolver(tmp_path / "models")

    with pytest.raises(
        WhisperModelNotReadyError,
        match="small.*not installed locally",
    ):
        resolve_ready_whisper_model(
            resolver,
            WhisperModel.SMALL,
        )
