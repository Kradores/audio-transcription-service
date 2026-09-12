from __future__ import annotations

import argparse
import hashlib
import logging
import statistics
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from pydantic import BaseModel

from app.composition import create_whisper_model
from app.core.config.constants import DEFAULT_CONFIGURATION_PATH
from app.core.config.loader import ConfigurationLoader


class CaptureMetadata(BaseModel):
    selected_language: str | None
    sample_rate: int
    sample_count: int
    dtype: str
    audio_sha256: str
    inference_duration_seconds: float


@dataclass(frozen=True, slots=True)
class ReplayTiming:
    total_seconds: float
    setup_seconds: float
    decoding_seconds: float


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Replay an exact slow Faster-Whisper input.",
    )

    parser.add_argument(
        "capture_directory",
        type=Path,
    )

    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIGURATION_PATH,
    )

    parser.add_argument(
        "--iterations",
        type=int,
        default=20,
    )

    parser.add_argument(
        "--language",
        default="original",
        help="original, auto, or an explicit language code such as ro/en/ru",
    )

    parser.add_argument(
        "--debug-faster-whisper",
        action="store_true",
    )

    parser.add_argument(
        "--print-text",
        action="store_true",
    )

    return parser.parse_args()


def load_capture(
    capture_directory: Path,
) -> tuple[np.ndarray, CaptureMetadata]:
    metadata_path = capture_directory / "metadata.json"
    audio_path = capture_directory / "audio.npy"

    metadata = CaptureMetadata.model_validate_json(
        metadata_path.read_text(encoding="utf-8"),
    )

    audio = np.load(
        audio_path,
        allow_pickle=False,
    )

    if audio.dtype != np.float32:
        raise ValueError(
            f"expected float32 audio, got {audio.dtype}",
        )

    if audio.ndim != 1:
        raise ValueError(
            f"expected one-dimensional audio, got shape={audio.shape}",
        )

    if audio.shape[0] != metadata.sample_count:
        raise ValueError(
            "captured audio sample count does not match metadata",
        )

    actual_sha256 = hashlib.sha256(
        np.ascontiguousarray(audio).tobytes(order="C"),
    ).hexdigest()

    if actual_sha256 != metadata.audio_sha256:
        raise ValueError(
            "captured audio SHA-256 does not match metadata",
        )

    return audio, metadata


def resolve_language(
    value: str,
    metadata: CaptureMetadata,
) -> str | None:
    if value == "original":
        return metadata.selected_language

    if value == "auto":
        return None

    return value


def main() -> None:
    args = parse_args()

    if args.iterations < 1:
        raise ValueError("--iterations must be at least 1")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )

    if args.debug_faster_whisper:
        logging.getLogger("faster_whisper").setLevel(logging.DEBUG)

    audio, metadata = load_capture(
        args.capture_directory.resolve(),
    )

    settings = ConfigurationLoader(
        args.config,
    ).load()

    language = resolve_language(
        args.language,
        metadata,
    )

    print(
        "capture loaded "
        f"samples={audio.shape[0]} "
        f"sample_rate={metadata.sample_rate} "
        f"duration={audio.shape[0] / metadata.sample_rate:.3f}s "
        f"original_language={metadata.selected_language or 'auto'} "
        f"replay_language={language or 'auto'} "
        f"original_inference={metadata.inference_duration_seconds:.3f}s"
    )

    model = create_whisper_model(settings)

    timings: list[ReplayTiming] = []

    for iteration in range(1, args.iterations + 1):
        started_at = time.perf_counter()

        whisper_segments, info = model.transcribe(
            audio,
            language=language,
        )

        setup_completed_at = time.perf_counter()

        segments = list(whisper_segments)

        completed_at = time.perf_counter()

        text = " ".join(segment.text.strip() for segment in segments if segment.text.strip())

        setup_seconds = setup_completed_at - started_at
        decoding_seconds = completed_at - setup_completed_at
        total_seconds = completed_at - started_at

        timings.append(
            ReplayTiming(
                total_seconds=total_seconds,
                setup_seconds=setup_seconds,
                decoding_seconds=decoding_seconds,
            )
        )

        print(
            f"iteration={iteration} "
            f"total={total_seconds:.3f}s "
            f"setup={setup_seconds:.3f}s "
            f"decoding={decoding_seconds:.3f}s "
            f"language={info.language} "
            f"confidence={info.language_probability:.3f} "
            f"segments={len(segments)} "
            f"characters={len(text)}"
        )

        if args.print_text:
            print(f"text={text!r}")

    totals = [timing.total_seconds for timing in timings]
    decoding = [timing.decoding_seconds for timing in timings]

    print()
    print(
        "summary "
        f"iterations={len(timings)} "
        f"total_mean={statistics.mean(totals):.3f}s "
        f"total_median={statistics.median(totals):.3f}s "
        f"total_max={max(totals):.3f}s "
        f"decoding_mean={statistics.mean(decoding):.3f}s "
        f"decoding_max={max(decoding):.3f}s"
    )


if __name__ == "__main__":
    main()
