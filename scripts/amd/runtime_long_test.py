from __future__ import annotations

import argparse
import gc
import statistics
import time
from pathlib import Path

PRELOAD_LIBRARIES = [
    "amd_comgr",
    "amdhip64",
    "hipblas",
    "hiprand",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--audio-fixture",
        type=Path,
        required=True,
    )
    parser.add_argument(
        "--duration-seconds",
        type=int,
        required=True,
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if args.duration_seconds <= 0:
        raise ValueError("duration-seconds must be greater than zero.")

    if not args.audio_fixture.is_file():
        raise FileNotFoundError(args.audio_fixture)

    print(
        "Initializing TheRock runtime...",
        flush=True,
    )

    import rocm_sdk  # type: ignore[import-not-found]

    rocm_sdk.initialize_process(
        preload_shortnames=PRELOAD_LIBRARIES,
    )

    print(
        "Creating Faster-Whisper model...",
        flush=True,
    )

    from faster_whisper import WhisperModel  # type: ignore[import-untyped]

    model = WhisperModel(
        "small",
        device="cuda",
        compute_type="float16",
        num_workers=1,
    )

    started_at = time.monotonic()
    deadline = started_at + args.duration_seconds

    inference_durations: list[float] = []
    transcription_count = 0

    print(
        f"Starting long-running GPU workload duration_seconds={args.duration_seconds}",
        flush=True,
    )

    while time.monotonic() < deadline:
        inference_started_at = time.monotonic()

        segments_iterator, info = model.transcribe(
            str(args.audio_fixture),
        )

        segments = list(segments_iterator)

        inference_duration = time.monotonic() - inference_started_at

        text = " ".join(
            segment.text.strip() for segment in segments if segment.text.strip()
        ).strip()

        if not text:
            raise RuntimeError("Faster-Whisper returned an empty transcription.")

        if info.language != "en":
            raise RuntimeError(f"Unexpected language detection: expected=en actual={info.language}")

        inference_durations.append(inference_duration)
        transcription_count += 1

        if transcription_count % 25 == 0:
            elapsed = time.monotonic() - started_at

            print(
                "Progress "
                f"transcriptions={transcription_count} "
                f"elapsed_seconds={elapsed:.1f} "
                f"last_inference_seconds={inference_duration:.3f}",
                flush=True,
            )

    workload_duration = time.monotonic() - started_at

    if transcription_count == 0:
        raise RuntimeError("Long-running workload performed no transcriptions.")

    average_inference = statistics.fmean(inference_durations)

    maximum_inference = max(inference_durations)

    print(
        "Long-running workload completed "
        f"transcriptions={transcription_count} "
        f"duration_seconds={workload_duration:.1f} "
        f"average_inference_seconds={average_inference:.3f} "
        f"maximum_inference_seconds={maximum_inference:.3f}",
        flush=True,
    )

    print(
        "Destroying Faster-Whisper model...",
        flush=True,
    )

    teardown_started_at = time.monotonic()

    del segments
    del segments_iterator
    del model

    gc.collect()

    teardown_duration = time.monotonic() - teardown_started_at

    print(
        f"Model destruction completed duration_seconds={teardown_duration:.3f}",
        flush=True,
    )

    print(
        "AMD long-running teardown regression passed.",
        flush=True,
    )


if __name__ == "__main__":
    main()
