from __future__ import annotations

import argparse
import hashlib
import logging
import statistics
import time
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, cast

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


class ReplaySegment(Protocol):
    text: str
    tokens: list[int]


@dataclass(frozen=True, slots=True)
class ReplayResult:
    total_seconds: float
    setup_seconds: float
    decoding_seconds: float
    language: str
    confidence: float
    output_segments: int
    output_tokens: int
    text: str


class ReplayInfo(Protocol):
    language: str
    language_probability: float


class ReplayWhisperModel(Protocol):
    def transcribe(
        self,
        audio: np.ndarray,
        *,
        language: str | None = None,
        temperature: float | list[float] | tuple[float, ...] = ...,
        max_new_tokens: int | None = ...,
    ) -> tuple[Iterable[ReplaySegment], ReplayInfo]:
        """Transcribe audio using optional diagnostic decoding overrides."""


@dataclass(frozen=True, slots=True)
class ReplayTiming:
    total_seconds: float
    setup_seconds: float
    decoding_seconds: float


@dataclass(frozen=True, slots=True)
class ReplayDecodingOverrides:
    temperature: float | None = None
    max_new_tokens: int | None = None

    def validate(self) -> None:
        if self.temperature is not None and self.temperature < 0.0:
            raise ValueError("--temperature must not be negative")

        if self.max_new_tokens is not None and self.max_new_tokens < 1:
            raise ValueError("--max-new-tokens must be at least 1")


def run_replay_once(
    *,
    model: ReplayWhisperModel,
    audio: np.ndarray,
    language: str | None,
    overrides: ReplayDecodingOverrides,
) -> ReplayResult:
    started_at = time.perf_counter()

    whisper_segments, info = transcribe_with_overrides(
        model=model,
        audio=audio,
        language=language,
        overrides=overrides,
    )

    setup_completed_at = time.perf_counter()

    segments = list(whisper_segments)

    completed_at = time.perf_counter()

    text = " ".join(segment.text.strip() for segment in segments if segment.text.strip())

    return ReplayResult(
        total_seconds=completed_at - started_at,
        setup_seconds=setup_completed_at - started_at,
        decoding_seconds=completed_at - setup_completed_at,
        language=info.language,
        confidence=info.language_probability,
        output_segments=len(segments),
        output_tokens=sum(len(segment.tokens) for segment in segments),
        text=text,
    )


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
        "--temperature",
        type=float,
        default=None,
        help=(
            "Override Faster-Whisper temperature with one value. "
            "Omit to preserve Faster-Whisper's default temperature fallback sequence."
        ),
    )

    parser.add_argument(
        "--max-new-tokens",
        type=int,
        default=None,
        help=(
            "Maximum newly generated tokens per Whisper decoding window. "
            "Omit to preserve Faster-Whisper's default model limit."
        ),
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


def transcribe_with_overrides(
    *,
    model: ReplayWhisperModel,
    audio: np.ndarray,
    language: str | None,
    overrides: ReplayDecodingOverrides,
) -> tuple[Iterable[ReplaySegment], ReplayInfo]:
    if overrides.temperature is None and overrides.max_new_tokens is None:
        return model.transcribe(
            audio,
            language=language,
        )

    if overrides.temperature is None:
        return model.transcribe(
            audio,
            language=language,
            max_new_tokens=overrides.max_new_tokens,
        )

    if overrides.max_new_tokens is None:
        return model.transcribe(
            audio,
            language=language,
            temperature=overrides.temperature,
        )

    return model.transcribe(
        audio,
        language=language,
        temperature=overrides.temperature,
        max_new_tokens=overrides.max_new_tokens,
    )


def describe_overrides(
    overrides: ReplayDecodingOverrides,
) -> str:
    temperature = (
        "default-fallback" if overrides.temperature is None else f"{overrides.temperature:.2f}"
    )

    max_new_tokens = (
        "model-default" if overrides.max_new_tokens is None else str(overrides.max_new_tokens)
    )

    return f"temperature={temperature} max_new_tokens={max_new_tokens}"


def main() -> None:
    args = parse_args()

    if args.iterations < 1:
        raise ValueError("--iterations must be at least 1")

    overrides = ReplayDecodingOverrides(
        temperature=args.temperature,
        max_new_tokens=args.max_new_tokens,
    )
    overrides.validate()

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
        f"original_inference={metadata.inference_duration_seconds:.3f}s "
        f"{describe_overrides(overrides)}"
    )

    model = cast(
        ReplayWhisperModel,
        create_whisper_model(settings),
    )

    timings: list[ReplayTiming] = []

    for iteration in range(1, args.iterations + 1):
        result = run_replay_once(
            model=model,
            audio=audio,
            language=language,
            overrides=overrides,
        )

        timings.append(
            ReplayTiming(
                total_seconds=result.total_seconds,
                setup_seconds=result.setup_seconds,
                decoding_seconds=result.decoding_seconds,
            )
        )

        print(
            f"iteration={iteration} "
            f"total={result.total_seconds:.3f}s "
            f"setup={result.setup_seconds:.3f}s "
            f"decoding={result.decoding_seconds:.3f}s "
            f"language={result.language} "
            f"confidence={result.confidence:.3f} "
            f"segments={result.output_segments} "
            f"tokens={result.output_tokens} "
            f"characters={len(result.text)}"
        )

        if args.print_text:
            print(f"text={result.text!r}")

    totals = [timing.total_seconds for timing in timings]
    decoding = [timing.decoding_seconds for timing in timings]

    print()
    print(
        "summary "
        f"iterations={len(timings)} "
        f"{describe_overrides(overrides)} "
        f"total_mean={statistics.mean(totals):.3f}s "
        f"total_median={statistics.median(totals):.3f}s "
        f"total_max={max(totals):.3f}s "
        f"decoding_mean={statistics.mean(decoding):.3f}s "
        f"decoding_max={max(decoding):.3f}s"
    )


if __name__ == "__main__":
    main()
