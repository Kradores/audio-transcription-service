from __future__ import annotations

import ctypes
import gc
import hashlib
import json
import os
import platform
import subprocess
import sys
import traceback
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TextIO


def bundle_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]

    return Path(__file__).resolve().parent


def executable_directory() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent

    return Path(__file__).resolve().parent


def sha256(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as file:
        for chunk in iter(
            lambda: file.read(1024 * 1024),
            b"",
        ):
            digest.update(chunk)

    return digest.hexdigest().upper()


class Tee:
    def __init__(
        self,
        *streams: TextIO,
    ) -> None:
        self._streams = streams

    def write(
        self,
        text: str,
    ) -> int:
        for stream in self._streams:
            stream.write(text)
            stream.flush()

        return len(text)

    def flush(self) -> None:
        for stream in self._streams:
            stream.flush()


def load_json(
    path: Path,
) -> dict[str, Any]:
    with path.open(
        "r",
        encoding="utf-8-sig",
    ) as file:
        document: object = json.load(file)

    if not isinstance(document, dict):
        raise RuntimeError(f"Expected JSON object: {path}")

    return document


def query_nvidia_smi() -> str:
    command = [
        "nvidia-smi",
        "--query-gpu=name,driver_version",
        "--format=csv,noheader",
    ]

    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return f"unavailable ({type(exc).__name__}: {exc})"

    output = result.stdout.strip()

    if result.returncode != 0:
        error = result.stderr.strip()

        return f"failed exit_code={result.returncode} error={error}"

    return output or "no GPU information returned"


def validate_runtime_files(
    *,
    runtime_directory: Path,
    manifest: dict[str, Any],
) -> tuple[Path, ...]:
    files = manifest.get("files")

    if not isinstance(files, list):
        raise RuntimeError("NVIDIA runtime manifest does not contain files")

    validated: list[Path] = []

    for entry in files:
        if not isinstance(entry, dict):
            raise RuntimeError("Invalid runtime manifest file entry")

        name = entry.get("name")
        expected_hash = entry.get("sha256")

        if not isinstance(name, str):
            raise RuntimeError("Runtime manifest file name is invalid")

        if not isinstance(expected_hash, str):
            raise RuntimeError(f"Runtime manifest hash is invalid: {name}")

        path = runtime_directory / name

        if not path.is_file():
            raise RuntimeError(f"Required NVIDIA runtime DLL is missing: {path}")

        actual_hash = sha256(path)

        if actual_hash != expected_hash:
            raise RuntimeError(
                "NVIDIA runtime DLL hash mismatch: "
                f"name={name} "
                f"expected={expected_hash} "
                f"actual={actual_hash}"
            )

        validated.append(path)

    return tuple(validated)


def configure_windows_dll_search(
    runtime_directory: Path,
) -> object:
    if os.name != "nt":
        raise RuntimeError("NVIDIA smoke test supports Windows only")

    current_path = os.environ.get(
        "PATH",
        "",
    )

    os.environ["PATH"] = f"{runtime_directory}{os.pathsep}{current_path}"

    return os.add_dll_directory(
        str(runtime_directory),
    )


def preload_runtime(
    *,
    runtime_directory: Path,
    names: Iterable[str],
) -> list[ctypes.CDLL]:
    loaded: list[ctypes.CDLL] = []

    for name in names:
        path = runtime_directory / name

        print(f"Preloading {name}...", flush=True)

        loaded.append(ctypes.WinDLL(str(path)))

    return loaded


def run_smoke_test() -> None:
    root = bundle_root()

    runtime_directory = root / "nvidia-runtime"
    manifest_path = runtime_directory / "manifest.json"
    fixture_path = root / "fixtures" / "english_speech.wav"

    if not fixture_path.is_file():
        raise RuntimeError(f"Audio fixture not found: {fixture_path}")

    manifest = load_json(manifest_path)

    print(
        "Audio Transcription Service - NVIDIA Runtime Smoke Test",
        flush=True,
    )

    print(
        f"Timestamp: {datetime.now(UTC).isoformat()}",
        flush=True,
    )
    print(
        f"Windows: {platform.platform()}",
        flush=True,
    )
    print(
        f"NVIDIA: {query_nvidia_smi()}",
        flush=True,
    )

    validated_dlls = validate_runtime_files(
        runtime_directory=runtime_directory,
        manifest=manifest,
    )

    print(
        f"NVIDIA runtime DLLs validated: {len(validated_dlls)}",
        flush=True,
    )

    dll_directory_handle = configure_windows_dll_search(
        runtime_directory,
    )

    # Preload the runtime explicitly before CTranslate2
    # is imported. This keeps the smoke test independent
    # of machine-wide CUDA PATH configuration.
    preload_order = (
        "cublasLt64_12.dll",
        "cublas64_12.dll",
        "nvrtc-builtins64_124.dll",
        "nvrtc64_120_0.dll",
        "cudnn_graph64_9.dll",
        "cudnn_ops64_9.dll",
        "cudnn_adv64_9.dll",
        "cudnn_cnn64_9.dll",
        "cudnn_heuristic64_9.dll",
        "cudnn_engines_precompiled64_9.dll",
        "cudnn_engines_runtime_compiled64_9.dll",
        "cudnn64_9.dll",
    )

    loaded_libraries = preload_runtime(
        runtime_directory=runtime_directory,
        names=preload_order,
    )

    print(
        "Importing CTranslate2...",
        flush=True,
    )

    import ctranslate2  # type: ignore[import-untyped]

    print(
        f"CTranslate2 version: {ctranslate2.__version__}",
        flush=True,
    )

    if ctranslate2.__version__ != "4.8.1":
        raise RuntimeError(f"Unexpected CTranslate2 version: {ctranslate2.__version__}")

    gpu_count = ctranslate2.get_cuda_device_count()

    print(
        f"CUDA device count: {gpu_count}",
        flush=True,
    )

    if gpu_count < 1:
        raise RuntimeError("CTranslate2 did not detect a CUDA GPU")

    compute_types = sorted(ctranslate2.get_supported_compute_types("cuda"))

    print(
        "CUDA compute types: " + ", ".join(compute_types),
        flush=True,
    )

    if "float16" not in compute_types:
        raise RuntimeError("CUDA runtime does not report float16 support")

    print(
        "Creating Faster-Whisper small model...",
        flush=True,
    )

    from faster_whisper import (  # type: ignore[import-untyped]
        WhisperModel,
    )

    model = WhisperModel(
        "small",
        device="cuda",
        compute_type="float16",
        num_workers=1,
    )

    print(
        "Running real GPU transcription...",
        flush=True,
    )

    segments_iterator, info = model.transcribe(
        str(fixture_path),
    )

    segments = list(segments_iterator)

    text = " ".join(segment.text.strip() for segment in segments if segment.text.strip()).strip()

    if not text:
        raise RuntimeError("Faster-Whisper returned an empty transcription")

    print(
        f"Detected language: {info.language}",
        flush=True,
    )

    print(
        f"Segments: {len(segments)}",
        flush=True,
    )

    print(
        f"Transcript: {text}",
        flush=True,
    )

    print(
        "Destroying Faster-Whisper model...",
        flush=True,
    )

    del segments
    del segments_iterator
    del model

    gc.collect()

    # Keep these objects alive until all GPU work and model
    # destruction are complete.
    _ = loaded_libraries
    _ = dll_directory_handle

    print(
        "Model destruction completed.",
        flush=True,
    )

    print("", flush=True)
    print(
        "NVIDIA RUNTIME SMOKE TEST PASSED",
        flush=True,
    )


def main() -> int:
    output_directory = executable_directory()

    log_path = output_directory / "nvidia-smoke-test.log"

    try:
        with log_path.open(
            "w",
            encoding="utf-8",
        ) as log_file:
            original_stdout = sys.stdout
            original_stderr = sys.stderr

            tee = Tee(
                original_stdout,
                log_file,
            )

            sys.stdout = tee  # type: ignore[assignment]
            sys.stderr = tee  # type: ignore[assignment]

            try:
                run_smoke_test()
            except Exception:
                print("", flush=True)
                print(
                    "NVIDIA RUNTIME SMOKE TEST FAILED",
                    flush=True,
                )
                print("", flush=True)

                traceback.print_exc()

                return 1
            finally:
                sys.stdout = original_stdout
                sys.stderr = original_stderr
    except OSError as exc:
        print(
            f"Could not create smoke-test log: {exc}",
            flush=True,
        )
        return 1

    return 0


if __name__ == "__main__":
    exit_code = main()

    print("")
    print(
        "Log file:",
        executable_directory() / "nvidia-smoke-test.log",
    )
    print("")
    input("Press Enter to close...")

    raise SystemExit(exit_code)
