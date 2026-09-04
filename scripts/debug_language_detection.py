from __future__ import annotations

import argparse
import csv
import re
import time
import wave
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Protocol, cast

import numpy as np

from app.audio.contracts import AudioFormat, AudioFrame
from app.audio.normalizer import AudioNormalizerImpl
from app.audio.resampler import SoXRResamplerFactory
from app.composition import create_whisper_model
from app.core.config.loader import ConfigurationLoader
from app.core.config.models import AudioProcessingSettings
from app.transcription.protocols import WhisperModelProtocol

PROJECT_ROOT = Path(__file__).resolve().parents[1]

DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "config.yaml"
DEFAULT_FIXTURE_DIRECTORY = PROJECT_ROOT / "tests" / "fixtures" / "audio"
DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "logs" / "language-detection-benchmark.csv"

NAMED_FIXTURE_PATTERN = re.compile(
    r"^(?P<language>[a-z]{2})_"
    r"(?P<named_duration>\d+(?:\.\d*)?s)_"
    r"(?P<fixture_id>\d+)"
    r"(?:_(?P<notes>.+))?"
    r"\.wav$"
)

CAPTURED_FIXTURE_PATTERN = re.compile(
    r"^(?P<language>[a-z]{2})_"
    r"(?P<timestamp>\d+(?:\.\d+)?)_"
    r"(?P<duration>\d+(?:\.\d+)?)"
    r"(?:_(?P<notes>.+))?"
    r"\.wav$"
)

type LanguageProbabilities = list[tuple[str, float]]


class LanguageDetectingWhisperModel(Protocol):
    def detect_language(
        self,
        audio: np.ndarray,
        *,
        vad_filter: bool = False,
        language_detection_segments: int = 1,
        language_detection_threshold: float = 0.5,
    ) -> tuple[str, float, LanguageProbabilities]:
        """Detect the language of normalized 16 kHz mono audio."""


@dataclass(frozen=True)
class AudioFixture:
    name: str
    expected_language: str
    fixture_group: str
    component_files: str
    audio: np.ndarray
    duration_seconds: float


@dataclass(frozen=True)
class BenchmarkResult:
    fixture: str
    fixture_group: str
    component_files: str
    expected_language: str
    duration_seconds: float
    rms: float
    peak: float
    method: str
    repetition: int
    detected_language: str
    probability: float
    second_language: str
    second_probability: float
    probability_margin: float
    elapsed_seconds: float
    transcript: str


def apply_gain(
    audio: np.ndarray,
    *,
    gain_db: float,
) -> np.ndarray:
    gain = 10 ** (gain_db / 20.0)

    amplified = audio * gain

    return np.ascontiguousarray(
        np.clip(
            amplified,
            -1.0,
            1.0,
        ),
        dtype=np.float32,
    )


def peak_normalize(
    audio: np.ndarray,
    *,
    target_peak: float = 0.95,
) -> np.ndarray:
    peak = float(np.max(np.abs(audio)))

    if peak == 0.0:
        return audio.copy()

    normalized = audio * (target_peak / peak)

    return np.ascontiguousarray(
        normalized,
        dtype=np.float32,
    )


def rms_normalize(
    audio: np.ndarray,
    *,
    target_dbfs: float = -20.0,
) -> np.ndarray:
    rms = float(
        np.sqrt(
            np.mean(
                np.square(audio),
            )
        )
    )

    if rms == 0.0:
        return audio.copy()

    target_rms = 10 ** (target_dbfs / 20.0)

    normalized = audio * (target_rms / rms)

    return np.ascontiguousarray(
        np.clip(
            normalized,
            -1.0,
            1.0,
        ),
        dtype=np.float32,
    )


def create_gain_variants(
    fixtures: list[AudioFixture],
) -> list[AudioFixture]:
    variants: list[AudioFixture] = []

    for fixture in fixtures:
        if fixture.fixture_group != "microphone":
            continue

        gain_variants = (
            ("gain_6db", apply_gain(fixture.audio, gain_db=6.0)),
            ("gain_12db", apply_gain(fixture.audio, gain_db=12.0)),
            ("gain_18db", apply_gain(fixture.audio, gain_db=18.0)),
            ("peak_normalized", peak_normalize(fixture.audio)),
            ("rms_normalized", rms_normalize(fixture.audio)),
        )

        for variant_name, audio in gain_variants:
            variants.append(
                AudioFixture(
                    name=f"{fixture.name}_{variant_name}",
                    expected_language=fixture.expected_language,
                    fixture_group=f"microphone_{variant_name}",
                    component_files=fixture.component_files,
                    audio=audio,
                    duration_seconds=fixture.duration_seconds,
                )
            )

    return variants


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Compare Faster-Whisper transcription language detection "
            "with standalone language detection."
        )
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
    )
    parser.add_argument(
        "--fixtures",
        type=Path,
        default=DEFAULT_FIXTURE_DIRECTORY,
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
    )
    parser.add_argument(
        "--repetitions",
        type=int,
        default=1,
    )
    parser.add_argument(
        "--separator-seconds",
        type=float,
        default=0.25,
    )

    arguments = parser.parse_args()

    if arguments.repetitions <= 0:
        parser.error("--repetitions must be greater than zero")

    if arguments.separator_seconds < 0.0:
        parser.error("--separator-seconds must not be negative")

    return arguments


def read_pcm16_wav(path: Path) -> AudioFrame:
    with wave.open(str(path), "rb") as wav_file:
        sample_rate = wav_file.getframerate()
        channels = wav_file.getnchannels()
        sample_width = wav_file.getsampwidth()
        frame_count = wav_file.getnframes()
        audio_bytes = wav_file.readframes(frame_count)

    if sample_width != 2:
        raise ValueError(f"Fixture must be PCM16: {path} sample_width={sample_width}")

    samples = np.frombuffer(
        audio_bytes,
        dtype=np.int16,
    )
    audio = samples.reshape(
        -1,
        channels,
    )

    return AudioFrame(
        audio=audio,
        timestamp=0.0,
        format=AudioFormat(
            sample_rate=sample_rate,
            channels=channels,
            sample_type="int16",
        ),
    )


def normalize_fixture(
    *,
    path: Path,
    settings: AudioProcessingSettings,
) -> np.ndarray:
    # The caller passes settings.audio.processing. Keeping the annotation
    # local would unnecessarily duplicate the concrete config model here.
    normalizer = AudioNormalizerImpl(
        settings=settings,
        resampler_factory=SoXRResamplerFactory(),
    )

    frame = read_pcm16_wav(path)

    processing_frames = normalizer.process(frame) + normalizer.flush()

    if not processing_frames:
        raise ValueError(f"Fixture produced no normalized audio: {path}")

    audio = np.concatenate(
        [processing_frame.audio[:, 0] for processing_frame in processing_frames],
        axis=0,
    )

    return np.ascontiguousarray(
        audio,
        dtype=np.float32,
    )


def calculate_rms(
    audio: np.ndarray,
) -> float:
    return float(
        np.sqrt(
            np.mean(
                np.square(audio),
            )
        )
    )


def calculate_peak(
    audio: np.ndarray,
) -> float:
    return float(
        np.max(
            np.abs(audio),
        )
    )


def discover_fixtures(
    *,
    directory: Path,
    processing_settings: AudioProcessingSettings,
) -> list[AudioFixture]:
    fixtures: list[
        tuple[
            tuple[str, int, float],
            AudioFixture,
        ]
    ] = []

    for path in sorted(directory.glob("*.wav")):
        named_match = NAMED_FIXTURE_PATTERN.match(path.name)
        captured_match = CAPTURED_FIXTURE_PATTERN.match(path.name)

        if named_match is not None:
            fixture_group = "reference"
            expected_language = named_match.group("language")
            sort_key = (
                expected_language,
                0,
                float(named_match.group("fixture_id")),
            )

        elif captured_match is not None:
            fixture_group = "microphone"
            expected_language = captured_match.group("language")
            sort_key = (
                expected_language,
                1,
                float(captured_match.group("timestamp")),
            )

        else:
            continue

        audio = normalize_fixture(
            path=path,
            settings=processing_settings,
        )

        fixture = AudioFixture(
            name=path.stem,
            expected_language=expected_language,
            fixture_group=fixture_group,
            component_files=path.name,
            audio=audio,
            duration_seconds=audio.shape[0] / 16_000,
        )

        fixtures.append(
            (
                sort_key,
                fixture,
            )
        )

    fixtures.sort(
        key=lambda item: item[0],
    )

    return [fixture for _, fixture in fixtures]


def create_accumulated_fixtures(
    fixtures: list[AudioFixture],
    *,
    separator_seconds: float,
) -> list[AudioFixture]:
    accumulated: list[AudioFixture] = []

    separator = np.zeros(
        round(separator_seconds * 16_000),
        dtype=np.float32,
    )

    groups = sorted(
        {
            (
                fixture.fixture_group,
                fixture.expected_language,
            )
            for fixture in fixtures
        }
    )

    for fixture_group, language in groups:
        language_fixtures = [
            fixture
            for fixture in fixtures
            if fixture.fixture_group == fixture_group and fixture.expected_language == language
        ]

        if len(language_fixtures) < 2:
            continue

        audio_parts: list[np.ndarray] = []

        for index, fixture in enumerate(language_fixtures):
            if index > 0 and separator.size > 0:
                audio_parts.append(separator)

            audio_parts.append(fixture.audio)

        combined_audio = np.ascontiguousarray(
            np.concatenate(
                audio_parts,
                axis=0,
            ),
            dtype=np.float32,
        )

        accumulated.append(
            AudioFixture(
                name=f"{fixture_group}_{language}_accumulated_all",
                expected_language=language,
                fixture_group=fixture_group,
                component_files=" + ".join(
                    fixture.component_files for fixture in language_fixtures
                ),
                audio=combined_audio,
                duration_seconds=combined_audio.shape[0] / 16_000,
            )
        )

    return accumulated


def probability_details(
    detected_language: str,
    probability: float,
    probabilities: LanguageProbabilities | None,
) -> tuple[str, float, float]:
    if not probabilities:
        return "", 0.0, probability

    ordered = sorted(
        probabilities,
        key=lambda item: item[1],
        reverse=True,
    )

    second = next(
        (item for item in ordered if item[0] != detected_language),
        ("", 0.0),
    )

    return (
        second[0],
        second[1],
        probability - second[1],
    )


def run_transcription_detection(
    *,
    model: WhisperModelProtocol,
    fixture: AudioFixture,
    repetition: int,
) -> BenchmarkResult:
    started_at = time.perf_counter()

    segments, info = model.transcribe(
        fixture.audio,
        language=None,
    )

    transcript = " ".join(segment.text.strip() for segment in segments if segment.text.strip())

    elapsed_seconds = time.perf_counter() - started_at

    probabilities = cast(
        LanguageProbabilities | None,
        getattr(
            info,
            "all_language_probs",
            None,
        ),
    )

    second_language, second_probability, margin = probability_details(
        info.language,
        info.language_probability,
        probabilities,
    )

    return BenchmarkResult(
        fixture=fixture.name,
        fixture_group=fixture.fixture_group,
        component_files=fixture.component_files,
        expected_language=fixture.expected_language,
        duration_seconds=fixture.duration_seconds,
        rms=calculate_rms(fixture.audio),
        peak=calculate_peak(fixture.audio),
        method="transcribe_auto",
        repetition=repetition,
        detected_language=info.language,
        probability=info.language_probability,
        second_language=second_language,
        second_probability=second_probability,
        probability_margin=margin,
        elapsed_seconds=elapsed_seconds,
        transcript=transcript,
    )


def run_standalone_detection(
    *,
    model: LanguageDetectingWhisperModel,
    fixture: AudioFixture,
    repetition: int,
    vad_filter: bool,
) -> BenchmarkResult:
    started_at = time.perf_counter()

    language, probability, probabilities = model.detect_language(
        fixture.audio,
        vad_filter=vad_filter,
        language_detection_segments=1,
        language_detection_threshold=0.5,
    )

    elapsed_seconds = time.perf_counter() - started_at

    second_language, second_probability, margin = probability_details(
        language,
        probability,
        probabilities,
    )

    return BenchmarkResult(
        fixture=fixture.name,
        fixture_group=fixture.fixture_group,
        component_files=fixture.component_files,
        expected_language=fixture.expected_language,
        duration_seconds=fixture.duration_seconds,
        rms=calculate_rms(fixture.audio),
        peak=calculate_peak(fixture.audio),
        method=("detect_vad" if vad_filter else "detect_raw"),
        repetition=repetition,
        detected_language=language,
        probability=probability,
        second_language=second_language,
        second_probability=second_probability,
        probability_margin=margin,
        elapsed_seconds=elapsed_seconds,
        transcript="",
    )


def warm_up_model(
    model: WhisperModelProtocol,
    fixture: AudioFixture,
) -> None:
    segments, _ = model.transcribe(
        fixture.audio,
        language=fixture.expected_language,
    )

    list(segments)


def print_fixture_summary(
    fixtures: list[AudioFixture],
) -> None:
    print("\nFixtures")

    for fixture in fixtures:
        print(
            f"  {fixture.name:<28} "
            f"expected={fixture.expected_language:<2} "
            f"duration={fixture.duration_seconds:>6.3f}s "
            f"files={fixture.component_files}"
        )


def print_results(
    results: list[BenchmarkResult],
) -> None:
    print("\nResults")
    print(
        f"{'fixture':<28} "
        f"{'method':<15} "
        f"{'expected':<8} "
        f"{'detected':<8} "
        f"{'prob':>7} "
        f"{'second':<8} "
        f"{'margin':>7} "
        f"{'time':>7}"
    )

    for result in results:
        print(
            f"{result.fixture:<28} "
            f"{result.method:<15} "
            f"{result.expected_language:<8} "
            f"{result.detected_language:<8} "
            f"{result.probability:>7.3f} "
            f"{result.second_language:<8} "
            f"{result.probability_margin:>7.3f} "
            f"{result.elapsed_seconds:>7.3f}"
        )

        if result.transcript:
            print(f"  transcript={result.transcript!r}")


def write_results(
    path: Path,
    results: list[BenchmarkResult],
) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    field_names = [field.name for field in fields(BenchmarkResult)]

    with path.open(
        "w",
        encoding="utf-8",
        newline="",
    ) as output_file:
        writer = csv.DictWriter(
            output_file,
            fieldnames=field_names,
        )
        writer.writeheader()

        for result in results:
            writer.writerow(asdict(result))


def main() -> None:
    arguments = parse_arguments()

    settings = ConfigurationLoader(
        arguments.config,
    ).load()

    individual_fixtures = discover_fixtures(
        directory=arguments.fixtures,
        processing_settings=settings.audio.processing,
    )

    if not individual_fixtures:
        raise RuntimeError("No fixtures matched the expected naming convention")

    accumulated_fixtures = create_accumulated_fixtures(
        individual_fixtures,
        separator_seconds=arguments.separator_seconds,
    )

    gain_variants = create_gain_variants(
        individual_fixtures,
    )

    fixtures = [
        *individual_fixtures,
        *gain_variants,
        *accumulated_fixtures,
    ]

    print_fixture_summary(fixtures)

    model = create_whisper_model(settings)
    detection_model = cast(
        LanguageDetectingWhisperModel,
        model,
    )

    print("\nWarming up model...")
    warm_up_model(
        model,
        individual_fixtures[0],
    )

    results: list[BenchmarkResult] = []

    for repetition in range(
        1,
        arguments.repetitions + 1,
    ):
        for fixture in fixtures:
            results.append(
                run_transcription_detection(
                    model=model,
                    fixture=fixture,
                    repetition=repetition,
                )
            )
            results.append(
                run_standalone_detection(
                    model=detection_model,
                    fixture=fixture,
                    repetition=repetition,
                    vad_filter=False,
                )
            )
            results.append(
                run_standalone_detection(
                    model=detection_model,
                    fixture=fixture,
                    repetition=repetition,
                    vad_filter=True,
                )
            )

    print_results(results)
    write_results(
        arguments.output,
        results,
    )

    print(f"\nCSV written to: {arguments.output}")


if __name__ == "__main__":
    main()
