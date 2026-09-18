from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files


repository_root = Path(SPECPATH).resolve().parents[1]

entry_point = repository_root / "app" / "controller" / "windows_nvidia_main.py"

runtime_directory = repository_root / "build" / "nvidia-runtime"

distribution_metadata_path = (
    repository_root / "build" / "distribution-metadata" / "nvidia" / "distribution-metadata.json"
)

if not distribution_metadata_path.is_file():
    raise RuntimeError(f"NVIDIA distribution metadata does not exist: {distribution_metadata_path}")


if not runtime_directory.is_dir():
    raise RuntimeError(f"NVIDIA runtime staging directory does not exist: {runtime_directory}")


runtime_binaries = [
    (
        str(path),
        "nvidia-runtime",
    )
    for path in sorted(runtime_directory.glob("*.dll"))
]


analysis = Analysis(
    [str(entry_point)],
    pathex=[str(repository_root)],
    binaries=runtime_binaries,
    datas=(
        collect_data_files("silero_vad")
        + [
            (
                str(runtime_directory / "manifest.json"),
                "nvidia-runtime",
            ),
            (
                str(distribution_metadata_path),
                ".",
            ),
        ]
    ),
    hiddenimports=[
        "faster_whisper",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)


pyz = PYZ(
    analysis.pure,
)


exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="AudioTranscriptionService",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)


collection = COLLECT(
    exe,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="AudioTranscriptionService",
)
