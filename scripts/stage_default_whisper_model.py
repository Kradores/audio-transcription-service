from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from app.core.config.enums import WhisperModel
from app.models.whisper import (
    WHISPER_MODEL_ARTIFACT_PATTERNS,
    WHISPER_MODEL_READY_MARKER_NAME,
    WhisperModelValidationError,
    validate_ready_whisper_model_directory,
    validate_whisper_model_contents,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]

DEFAULT_MODEL = WhisperModel.SMALL

DEFAULT_SOURCE_DIRECTORY = PROJECT_ROOT / "models" / DEFAULT_MODEL.value

DEFAULT_OUTPUT_DIRECTORY = PROJECT_ROOT / "build" / "model-seed" / DEFAULT_MODEL.value


class WhisperModelStagingError(RuntimeError):
    """Raised when the default model cannot be staged."""


def stage_default_whisper_model(
    *,
    source_directory: Path,
    output_directory: Path,
) -> Path:
    source_directory = source_directory.resolve()
    output_directory = output_directory.resolve()

    try:
        validate_ready_whisper_model_directory(source_directory)
    except WhisperModelValidationError as exc:
        raise WhisperModelStagingError(f"Default Whisper model source is invalid: {exc}") from exc

    output_directory.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary_directory = output_directory.parent / f".{output_directory.name}.staging"

    shutil.rmtree(
        temporary_directory,
        ignore_errors=True,
    )

    temporary_directory.mkdir(
        parents=True,
    )

    try:
        _copy_model_artifacts(
            source_directory=source_directory,
            destination_directory=(temporary_directory),
        )

        validate_whisper_model_contents(temporary_directory)

        # Publish READY only after all model artifacts
        # have been successfully staged and validated.
        shutil.copy2(
            source_directory / WHISPER_MODEL_READY_MARKER_NAME,
            temporary_directory / WHISPER_MODEL_READY_MARKER_NAME,
        )

        validate_ready_whisper_model_directory(temporary_directory)

        if output_directory.exists():
            shutil.rmtree(output_directory)

        temporary_directory.replace(output_directory)

    except Exception:
        shutil.rmtree(
            temporary_directory,
            ignore_errors=True,
        )
        raise

    return output_directory


def _copy_model_artifacts(
    *,
    source_directory: Path,
    destination_directory: Path,
) -> None:
    copied_names: set[str] = set()

    for pattern in WHISPER_MODEL_ARTIFACT_PATTERNS:
        for source_path in sorted(source_directory.glob(pattern)):
            if not source_path.is_file():
                continue

            if source_path.name in copied_names:
                continue

            shutil.copy2(
                source_path,
                destination_directory / source_path.name,
            )

            copied_names.add(source_path.name)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=("Stage the READY default Whisper model for Windows installer packaging.")
    )

    parser.add_argument(
        "--source",
        type=Path,
        default=DEFAULT_SOURCE_DIRECTORY,
    )

    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_DIRECTORY,
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    output_directory = stage_default_whisper_model(
        source_directory=args.source,
        output_directory=args.output,
    )

    print(f"Default Whisper model '{DEFAULT_MODEL.value}' staged at '{output_directory}'.")


if __name__ == "__main__":
    main()
