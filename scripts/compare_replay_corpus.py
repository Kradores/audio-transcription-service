from __future__ import annotations

import argparse
import csv
import statistics
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import cast

import numpy as np

from app.composition import create_whisper_model
from app.core.config.constants import DEFAULT_CONFIGURATION_PATH
from app.core.config.loader import ConfigurationLoader
from scripts.replay_slow_inference import (
    ReplayDecodingOverrides,
    ReplayResult,
    ReplayWhisperModel,
    load_capture,
    resolve_language,
    run_replay_once,
)


@dataclass(frozen=True, slots=True)
class ComparisonAnalysis:
    similarity: float
    suspicious_reasons: tuple[str, ...]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Compare Faster-Whisper defaults against a bounded "
            "max_new_tokens candidate across a captured corpus."
        ),
    )

    parser.add_argument(
        "corpus_directory",
        type=Path,
    )

    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIGURATION_PATH,
    )

    parser.add_argument(
        "--from-name",
        default=None,
    )

    parser.add_argument(
        "--to-name",
        default=None,
    )

    parser.add_argument(
        "--max-new-tokens",
        type=int,
        default=64,
    )

    parser.add_argument(
        "--output",
        type=Path,
        default=Path("logs/replay-comparison.csv"),
    )

    return parser.parse_args()


def discover_capture_directories(
    root: Path,
    *,
    from_name: str | None,
    to_name: str | None,
) -> list[Path]:
    captures = sorted(
        path
        for path in root.iterdir()
        if path.is_dir() and (path / "audio.npy").is_file() and (path / "metadata.json").is_file()
    )

    if from_name is not None:
        captures = [path for path in captures if path.name >= from_name]

    if to_name is not None:
        captures = [path for path in captures if path.name <= to_name]

    return captures


def normalize_text(text: str) -> str:
    return " ".join(text.casefold().split())


def calculate_similarity(
    baseline: str,
    candidate: str,
) -> float:
    baseline_normalized = normalize_text(baseline)
    candidate_normalized = normalize_text(candidate)

    if not baseline_normalized and not candidate_normalized:
        return 1.0

    return SequenceMatcher(
        None,
        baseline_normalized,
        candidate_normalized,
    ).ratio()


def analyze_comparison(
    *,
    baseline: ReplayResult,
    candidate: ReplayResult,
    max_new_tokens: int,
) -> ComparisonAnalysis:
    reasons: list[str] = []

    similarity = calculate_similarity(
        baseline.text,
        candidate.text,
    )

    if baseline.text and not candidate.text:
        reasons.append("candidate_empty")

    if len(baseline.text) >= 20 and len(candidate.text) < len(baseline.text) * 0.75:
        reasons.append("candidate_much_shorter")

    if candidate.output_tokens >= max_new_tokens - 4:
        reasons.append("candidate_near_token_limit")

    if baseline.text and candidate.text and similarity < 0.70:
        reasons.append("low_text_similarity")

    if baseline.language != candidate.language:
        reasons.append("language_changed")

    return ComparisonAnalysis(
        similarity=similarity,
        suspicious_reasons=tuple(reasons),
    )


def replay_pair(
    *,
    model: ReplayWhisperModel,
    audio: np.ndarray,
    language: str | None,
    candidate_max_new_tokens: int,
    candidate_first: bool,
) -> tuple[ReplayResult, ReplayResult]:
    baseline_overrides = ReplayDecodingOverrides()

    candidate_overrides = ReplayDecodingOverrides(
        max_new_tokens=candidate_max_new_tokens,
    )

    if candidate_first:
        candidate = run_replay_once(
            model=model,
            audio=audio,
            language=language,
            overrides=candidate_overrides,
        )

        baseline = run_replay_once(
            model=model,
            audio=audio,
            language=language,
            overrides=baseline_overrides,
        )

        return baseline, candidate

    baseline = run_replay_once(
        model=model,
        audio=audio,
        language=language,
        overrides=baseline_overrides,
    )

    candidate = run_replay_once(
        model=model,
        audio=audio,
        language=language,
        overrides=candidate_overrides,
    )

    return baseline, candidate


def main() -> None:
    args = parse_args()

    if args.max_new_tokens < 1:
        raise ValueError(
            "--max-new-tokens must be at least 1",
        )

    corpus_directory = args.corpus_directory.resolve()

    captures = discover_capture_directories(
        corpus_directory,
        from_name=args.from_name,
        to_name=args.to_name,
    )

    if not captures:
        raise ValueError(
            "no captures matched the requested range",
        )

    settings = ConfigurationLoader(
        args.config,
    ).load()

    model = cast(
        ReplayWhisperModel,
        create_whisper_model(settings),
    )

    output_path = args.output.resolve()

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    rows: list[dict[str, str | float | bool]] = []

    for index, capture_directory in enumerate(
        captures,
        start=1,
    ):
        audio, metadata = load_capture(
            capture_directory,
        )

        language = resolve_language(
            "original",
            metadata,
        )

        # Alternate order to avoid systematically giving one
        # configuration a warm-cache advantage.
        baseline, candidate = replay_pair(
            model=model,
            audio=audio,
            language=language,
            candidate_max_new_tokens=args.max_new_tokens,
            candidate_first=index % 2 == 0,
        )

        analysis = analyze_comparison(
            baseline=baseline,
            candidate=candidate,
            max_new_tokens=args.max_new_tokens,
        )

        speedup = (
            baseline.total_seconds / candidate.total_seconds
            if candidate.total_seconds > 0.0
            else float("inf")
        )

        reasons = ",".join(
            analysis.suspicious_reasons,
        )

        row: dict[str, str | float | bool] = {
            "capture": capture_directory.name,
            "audio_duration_seconds": (metadata.sample_count / metadata.sample_rate),
            "language_selection": (metadata.selected_language or "auto"),
            "original_inference_seconds": (metadata.inference_duration_seconds),
            "baseline_seconds": baseline.total_seconds,
            "candidate_seconds": candidate.total_seconds,
            "speedup": speedup,
            "baseline_language": baseline.language,
            "candidate_language": candidate.language,
            "baseline_confidence": baseline.confidence,
            "candidate_confidence": candidate.confidence,
            "baseline_tokens": baseline.output_tokens,
            "candidate_tokens": candidate.output_tokens,
            "baseline_characters": len(baseline.text),
            "candidate_characters": len(candidate.text),
            "text_similarity": analysis.similarity,
            "suspicious": bool(
                analysis.suspicious_reasons,
            ),
            "suspicious_reasons": reasons,
            "baseline_text": baseline.text,
            "candidate_text": candidate.text,
        }

        rows.append(row)

        marker = "CHECK" if analysis.suspicious_reasons else "OK"

        print(
            f"[{index:03d}/{len(captures):03d}] "
            f"{marker} "
            f"{capture_directory.name} "
            f"audio={row['audio_duration_seconds']:.2f}s "
            f"default={baseline.total_seconds:.3f}s "
            f"candidate={candidate.total_seconds:.3f}s "
            f"tokens={baseline.output_tokens}"
            f"->{candidate.output_tokens} "
            f"similarity={analysis.similarity:.3f} "
            f"{reasons}"
        )

    fieldnames = list(rows[0])

    with output_path.open(
        "w",
        encoding="utf-8-sig",
        newline="",
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=fieldnames,
        )

        writer.writeheader()
        writer.writerows(rows)

    baseline_times = [float(row["baseline_seconds"]) for row in rows]
    candidate_times = [float(row["candidate_seconds"]) for row in rows]

    suspicious_count = sum(bool(row["suspicious"]) for row in rows)

    near_limit_count = sum(
        "candidate_near_token_limit" in str(row["suspicious_reasons"]) for row in rows
    )

    identical_count = sum(float(row["text_similarity"]) == 1.0 for row in rows)

    print()
    print(
        "summary "
        f"samples={len(rows)} "
        f"baseline_median={statistics.median(baseline_times):.3f}s "
        f"baseline_max={max(baseline_times):.3f}s "
        f"candidate_median={statistics.median(candidate_times):.3f}s "
        f"candidate_max={max(candidate_times):.3f}s "
        f"identical_text={identical_count} "
        f"suspicious={suspicious_count} "
        f"candidate_near_token_limit={near_limit_count}"
    )

    print(f"report={output_path}")


if __name__ == "__main__":
    main()
