from __future__ import annotations

import argparse
import ctypes
import hashlib
import importlib.metadata
import json
import os
import platform
import site
import sys
from ctypes import wintypes
from pathlib import Path
from typing import Any

THEROCK_DISTRIBUTIONS = (
    "rocm",
    "rocm-sdk-core",
    "rocm-sdk-devel",
    "rocm-sdk-device-gfx1031",
    "rocm-sdk-libraries",
)

PRELOAD_SHORTNAMES = (
    "amd_comgr",
    "amdhip64",
    "hipblas",
    "hiprand",
)

NATIVE_SUFFIXES = {
    ".dll",
    ".pyd",
    ".exe",
    ".lib",
    ".bc",
    ".co",
    ".hsaco",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--audio-fixture",
        type=Path,
        required=True,
    )

    parser.add_argument(
        "--output",
        type=Path,
        required=True,
    )

    parser.add_argument(
        "--model",
        default="small",
    )

    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)

    return digest.hexdigest().upper()


def is_under(
    path: Path,
    parent: Path,
) -> bool:
    path_value = os.path.normcase(str(path.resolve()))

    parent_value = os.path.normcase(str(parent.resolve()))

    try:
        return os.path.commonpath((path_value, parent_value)) == parent_value
    except ValueError:
        return False


def classify_module(
    path: Path,
    *,
    runtime_root: Path,
    windows_root: Path | None,
) -> str:
    if is_under(path, runtime_root):
        return "runtime"

    if windows_root is not None and is_under(path, windows_root):
        return "windows"

    return "external"


def loaded_modules(
    *,
    runtime_root: Path,
) -> dict[str, dict[str, str]]:
    if os.name != "nt":
        raise RuntimeError("Loaded-module inspection is supported on Windows only.")

    psapi = ctypes.WinDLL(
        "psapi",
        use_last_error=True,
    )
    kernel32 = ctypes.WinDLL(
        "kernel32",
        use_last_error=True,
    )

    enum_process_modules = psapi.EnumProcessModules
    enum_process_modules.argtypes = (
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.HMODULE),
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    )
    enum_process_modules.restype = wintypes.BOOL

    get_module_filename = psapi.GetModuleFileNameExW
    get_module_filename.argtypes = (
        wintypes.HANDLE,
        wintypes.HMODULE,
        wintypes.LPWSTR,
        wintypes.DWORD,
    )
    get_module_filename.restype = wintypes.DWORD

    get_current_process = kernel32.GetCurrentProcess
    get_current_process.argtypes = ()
    get_current_process.restype = wintypes.HANDLE

    process = get_current_process()

    capacity = 512

    while True:
        modules = (wintypes.HMODULE * capacity)()

        required_bytes = wintypes.DWORD()

        if not enum_process_modules(
            process,
            modules,
            ctypes.sizeof(modules),
            ctypes.byref(required_bytes),
        ):
            raise ctypes.WinError(ctypes.get_last_error())

        module_count = required_bytes.value // ctypes.sizeof(wintypes.HMODULE)

        if module_count <= capacity:
            break

        capacity = module_count + 128

    windows_value = os.environ.get("WINDIR")

    windows_root = Path(windows_value) if windows_value else None

    result: dict[
        str,
        dict[str, str],
    ] = {}

    for index in range(module_count):
        buffer = ctypes.create_unicode_buffer(32768)

        length = get_module_filename(
            process,
            modules[index],
            buffer,
            len(buffer),
        )

        if length == 0:
            continue

        path = Path(buffer.value).resolve()

        key = os.path.normcase(str(path))

        result[key] = {
            "path": str(path),
            "classification": (
                classify_module(
                    path,
                    runtime_root=runtime_root,
                    windows_root=windows_root,
                )
            ),
        }

    return result


def module_delta(
    before: dict[str, dict[str, str]],
    after: dict[str, dict[str, str]],
) -> list[dict[str, str]]:
    return [after[key] for key in sorted(after.keys() - before.keys())]


def inventory_distribution(
    name: str,
) -> dict[str, Any]:
    distribution = importlib.metadata.distribution(name)

    files = distribution.files or []

    entries: list[dict[str, Any]] = []

    total_size = 0
    native_size = 0

    for item in files:
        path = Path(str(distribution.locate_file(item))).resolve()

        if not path.is_file():
            continue

        size = path.stat().st_size
        total_size += size

        suffix = path.suffix.lower()

        native = suffix in NATIVE_SUFFIXES

        if native:
            native_size += size

        entry: dict[str, Any] = {
            "relative_path": str(item),
            "absolute_path": str(path),
            "size": size,
            "native": native,
        }

        if suffix in {
            ".dll",
            ".pyd",
        }:
            entry["sha256"] = sha256(path)

        entries.append(entry)

    return {
        "name": name,
        "version": distribution.version,
        "file_count": len(entries),
        "total_size": total_size,
        "native_size": native_size,
        "files": entries,
    }


def path_entries(
    value: str,
) -> list[str]:
    return [item for item in value.split(os.pathsep) if item]


def added_path_entries(
    before: str,
    after: str,
) -> list[str]:
    existing = {os.path.normcase(item) for item in path_entries(before)}

    return [item for item in path_entries(after) if os.path.normcase(item) not in existing]


def main() -> None:
    args = parse_args()

    if os.name != "nt":
        raise RuntimeError("AMD runtime inspection must run on Windows.")

    audio_fixture = args.audio_fixture.resolve()

    if not audio_fixture.is_file():
        raise RuntimeError(f"Audio fixture does not exist: {audio_fixture}")

    runtime_root = Path(sys.prefix).resolve()

    output_path = args.output.resolve()

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    report: dict[str, Any] = {
        "schema_version": 1,
        "python": {
            "version": sys.version,
            "executable": sys.executable,
            "prefix": str(runtime_root),
            "platform": platform.platform(),
            "site_packages": (site.getsitepackages()),
        },
        "distributions": {},
        "runtime": {},
        "loaded_modules": {},
    }

    print(
        "Inventorying TheRock distributions...",
        flush=True,
    )

    for name in THEROCK_DISTRIBUTIONS:
        report["distributions"][name] = inventory_distribution(name)

    baseline = loaded_modules(
        runtime_root=runtime_root,
    )

    print(
        "Importing rocm_sdk...",
        flush=True,
    )

    import rocm_sdk  # type: ignore[import-not-found]

    report["runtime"]["rocm_sdk_file"] = str(Path(rocm_sdk.__file__).resolve())

    after_rocm_import = loaded_modules(
        runtime_root=runtime_root,
    )

    report["loaded_modules"]["rocm_sdk_import"] = module_delta(
        baseline,
        after_rocm_import,
    )

    path_before = os.environ.get(
        "PATH",
        "",
    )

    print(
        "Initializing TheRock runtime...",
        flush=True,
    )

    rocm_sdk.initialize_process(preload_shortnames=list(PRELOAD_SHORTNAMES))

    path_after = os.environ.get(
        "PATH",
        "",
    )

    report["runtime"]["path_entries_added_by_rocm_sdk"] = added_path_entries(
        path_before,
        path_after,
    )

    after_rocm_init = loaded_modules(
        runtime_root=runtime_root,
    )

    report["loaded_modules"]["rocm_sdk_initialize"] = module_delta(
        after_rocm_import,
        after_rocm_init,
    )

    print(
        "Importing CTranslate2...",
        flush=True,
    )

    import ctranslate2  # type: ignore[import-untyped]

    after_ctranslate2_import = loaded_modules(
        runtime_root=runtime_root,
    )

    report["loaded_modules"]["ctranslate2_import"] = module_delta(
        after_rocm_init,
        after_ctranslate2_import,
    )

    ct2_package = Path(ctranslate2.__file__).resolve().parent

    ct2_dll = ct2_package / "ctranslate2.dll"

    openmp_dll = ct2_package / "libiomp5md.dll"

    report["runtime"]["ctranslate2"] = {
        "version": (ctranslate2.__version__),
        "package_path": str(ct2_package),
        "dll": {
            "path": str(ct2_dll),
            "sha256": sha256(ct2_dll),
        },
        "openmp": {
            "path": str(openmp_dll),
            "sha256": sha256(openmp_dll),
        },
    }

    print(
        "Querying AMD accelerator...",
        flush=True,
    )

    gpu_count = ctranslate2.get_cuda_device_count()

    compute_types = sorted(ctranslate2.get_supported_compute_types("cuda"))

    report["runtime"]["ctranslate2"]["cuda_device_count"] = gpu_count

    report["runtime"]["ctranslate2"]["supported_compute_types"] = compute_types

    after_gpu_query = loaded_modules(
        runtime_root=runtime_root,
    )

    report["loaded_modules"]["gpu_query"] = module_delta(
        after_ctranslate2_import,
        after_gpu_query,
    )

    if gpu_count < 1:
        raise RuntimeError("CTranslate2 did not detect an AMD accelerator.")

    if "float16" not in compute_types:
        raise RuntimeError("CTranslate2 does not report float16 support.")

    print(
        "Creating Faster-Whisper model...",
        flush=True,
    )

    from faster_whisper import WhisperModel  # type: ignore[import-untyped]

    model = WhisperModel(
        args.model,
        device="cuda",
        compute_type="float16",
        num_workers=1,
    )

    after_model_create = loaded_modules(
        runtime_root=runtime_root,
    )

    report["loaded_modules"]["model_create"] = module_delta(
        after_gpu_query,
        after_model_create,
    )

    print(
        "Running real inference...",
        flush=True,
    )

    segments_iterator, info = model.transcribe(str(audio_fixture))

    segments = list(segments_iterator)

    text = " ".join(segment.text.strip() for segment in segments if segment.text.strip()).strip()

    if not text:
        raise RuntimeError("Faster-Whisper returned an empty transcript.")

    after_inference = loaded_modules(
        runtime_root=runtime_root,
    )

    report["loaded_modules"]["inference"] = module_delta(
        after_model_create,
        after_inference,
    )

    report["runtime"]["inference"] = {
        "model": args.model,
        "language": info.language,
        "segments": len(segments),
        "transcript_non_empty": True,
    }

    final_modules = after_inference

    report["runtime"]["final_runtime_modules"] = [
        value
        for value in sorted(
            final_modules.values(),
            key=lambda item: item["path"].casefold(),
        )
        if value["classification"] != "windows"
    ]

    with output_path.open(
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            report,
            file,
            indent=2,
            ensure_ascii=False,
        )

    print(
        "",
        flush=True,
    )
    print(
        "AMD runtime dependency inspection passed.",
        flush=True,
    )
    print(
        f"Report: {output_path}",
        flush=True,
    )


if __name__ == "__main__":
    main()
