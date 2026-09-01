from __future__ import annotations

import argparse
import gc
import hashlib
from pathlib import Path


PRELOAD_LIBRARIES = [
    "amd_comgr",
    "amdhip64",
    "hipblas",
    "hiprand",
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)

    return digest.hexdigest().upper()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--audio-fixture",
        type=Path,
        required=True,
    )
    parser.add_argument(
        "--expected-ct2-version",
        required=True,
    )
    parser.add_argument(
        "--expected-ct2-dll-sha256",
        required=True,
    )
    parser.add_argument(
        "--expected-openmp-sha256",
        required=True,
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    print("Initializing TheRock runtime...", flush=True)

    import rocm_sdk

    rocm_sdk.initialize_process(
        preload_shortnames=PRELOAD_LIBRARIES,
    )

    print("Importing CTranslate2...", flush=True)

    import ctranslate2

    if ctranslate2.__version__ != args.expected_ct2_version:
        raise RuntimeError(
            "CTranslate2 version mismatch: "
            f"expected={args.expected_ct2_version} "
            f"actual={ctranslate2.__version__}"
        )

    package_path = Path(ctranslate2.__file__).parent
    ct2_dll_path = package_path / "ctranslate2.dll"
    openmp_dll_path = package_path / "libiomp5md.dll"

    actual_ct2_hash = sha256(ct2_dll_path)
    actual_openmp_hash = sha256(openmp_dll_path)

    if actual_ct2_hash != args.expected_ct2_dll_sha256:
        raise RuntimeError(
            "Installed CTranslate2 DLL hash mismatch: "
            f"expected={args.expected_ct2_dll_sha256} "
            f"actual={actual_ct2_hash}"
        )

    if actual_openmp_hash != args.expected_openmp_sha256:
        raise RuntimeError(
            "Installed Intel OpenMP DLL hash mismatch: "
            f"expected={args.expected_openmp_sha256} "
            f"actual={actual_openmp_hash}"
        )

    gpu_count = ctranslate2.get_cuda_device_count()

    if gpu_count < 1:
        raise RuntimeError(
            f"Expected at least one GPU, found {gpu_count}."
        )

    compute_types = ctranslate2.get_supported_compute_types("cuda")

    if "float16" not in compute_types:
        raise RuntimeError(
            "CTranslate2 HIP runtime does not report float16 support."
        )

    print(
        "CTranslate2 runtime ready "
        f"version={ctranslate2.__version__} "
        f"gpu_count={gpu_count}",
        flush=True,
    )

    print("Creating Faster-Whisper model...", flush=True)

    from faster_whisper import WhisperModel

    model = WhisperModel(
        "small",
        device="cuda",
        compute_type="float16",
        num_workers=1,
    )

    print("Running real GPU inference...", flush=True)

    segments_iterator, info = model.transcribe(
        str(args.audio_fixture),
    )

    segments = list(segments_iterator)

    text = " ".join(
        segment.text.strip()
        for segment in segments
        if segment.text.strip()
    ).strip()

    if not text:
        raise RuntimeError(
            "Faster-Whisper returned an empty transcription."
        )

    if info.language != "en":
        raise RuntimeError(
            "Unexpected language detection: "
            f"expected=en actual={info.language}"
        )

    print(
        "Inference completed "
        f"language={info.language} "
        f"segments={len(segments)}",
        flush=True,
    )

    print(f"Transcript: {text}", flush=True)

    print("Destroying Faster-Whisper model...", flush=True)

    del segments
    del segments_iterator
    del model

    gc.collect()

    print("Model destruction completed.", flush=True)
    print("AMD runtime smoke test passed.", flush=True)


if __name__ == "__main__":
    main()