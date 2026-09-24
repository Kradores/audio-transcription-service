from pathlib import Path

import pytest

from app.models.whisper import (
    WHISPER_MODEL_READY_MARKER_NAME,
)
from scripts.stage_default_whisper_model import (
    WhisperModelStagingError,
    stage_default_whisper_model,
)


def _write_model_contents(
    directory: Path,
    *,
    ready: bool,
) -> None:
    directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    (directory / "config.json").write_text(
        "{}",
        encoding="utf-8",
    )
    (directory / "model.bin").write_bytes(b"model")
    (directory / "tokenizer.json").write_text(
        "{}",
        encoding="utf-8",
    )
    (directory / "preprocessor_config.json").write_text(
        "{}",
        encoding="utf-8",
    )
    (directory / "vocabulary.txt").write_text(
        "hello",
        encoding="utf-8",
    )

    if ready:
        (directory / WHISPER_MODEL_READY_MARKER_NAME).touch()


def test_stage_default_model_publishes_ready_copy(
    tmp_path: Path,
) -> None:
    source = tmp_path / "models" / "small"
    output = tmp_path / "build" / "model-seed" / "small"

    _write_model_contents(
        source,
        ready=True,
    )

    result = stage_default_whisper_model(
        source_directory=source,
        output_directory=output,
    )

    assert result == output.resolve()

    assert (output / "config.json").is_file()
    assert (output / "model.bin").is_file()
    assert (output / "tokenizer.json").is_file()
    assert (output / "preprocessor_config.json").is_file()
    assert (output / "vocabulary.txt").is_file()
    assert (output / WHISPER_MODEL_READY_MARKER_NAME).is_file()


def test_stage_default_model_excludes_unrelated_files(
    tmp_path: Path,
) -> None:
    source = tmp_path / "models" / "small"
    output = tmp_path / "build" / "model-seed" / "small"

    _write_model_contents(
        source,
        ready=True,
    )

    (source / "unrelated.txt").write_text(
        "do not package",
        encoding="utf-8",
    )

    cache_file = source / ".cache" / "huggingface" / "metadata.json"
    cache_file.parent.mkdir(
        parents=True,
    )
    cache_file.write_text(
        "{}",
        encoding="utf-8",
    )

    stage_default_whisper_model(
        source_directory=source,
        output_directory=output,
    )

    assert not (output / "unrelated.txt").exists()

    assert not (output / ".cache").exists()


def test_stage_default_model_rejects_unpublished_source(
    tmp_path: Path,
) -> None:
    source = tmp_path / "models" / "small"
    output = tmp_path / "build" / "model-seed" / "small"

    _write_model_contents(
        source,
        ready=False,
    )

    with pytest.raises(
        WhisperModelStagingError,
        match="not published as ready",
    ):
        stage_default_whisper_model(
            source_directory=source,
            output_directory=output,
        )

    assert not output.exists()


def test_invalid_source_does_not_replace_existing_seed(
    tmp_path: Path,
) -> None:
    source = tmp_path / "models" / "small"
    output = tmp_path / "build" / "model-seed" / "small"

    source.mkdir(
        parents=True,
    )
    (source / WHISPER_MODEL_READY_MARKER_NAME).touch()

    output.mkdir(
        parents=True,
    )

    sentinel = output / "existing.txt"
    sentinel.write_text(
        "keep me",
        encoding="utf-8",
    )

    with pytest.raises(
        WhisperModelStagingError,
    ):
        stage_default_whisper_model(
            source_directory=source,
            output_directory=output,
        )

    assert sentinel.read_text(encoding="utf-8") == "keep me"
