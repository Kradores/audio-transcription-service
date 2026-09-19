from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files


repository_root = Path(SPECPATH).resolve().parents[1]

entry_point = (
    repository_root
    / "app"
    / "controller"
    / "windows_main.py"
)

runtime_directory = (
    repository_root
    / "build"
    / "amd-runtime"
)

distribution_metadata_path = (
    repository_root
    / "build"
    / "distribution-metadata"
    / "amd"
    / "distribution-metadata.json"
)


if not runtime_directory.is_dir():
    raise RuntimeError(
        "AMD runtime staging directory does not exist: "
        f"{runtime_directory}"
    )


if not distribution_metadata_path.is_file():
    raise RuntimeError(
        "AMD distribution metadata does not exist: "
        f"{distribution_metadata_path}"
    )


runtime_datas = [
    (
        str(path),
        str(
            path.parent.relative_to(
                runtime_directory
            )
        ),
    )
    for path in sorted(
        runtime_directory.rglob("*")
    )
    if path.is_file()
]


analysis = Analysis(
    [str(entry_point)],
    pathex=[str(repository_root)],
    binaries=[],
    datas=(
        collect_data_files("silero_vad")
        + runtime_datas
        + [
            (
                str(
                    distribution_metadata_path
                ),
                ".",
            )
        ]
    ),
    hiddenimports=[
        "faster_whisper",
        "rocm_sdk",
        "_rocm_sdk_core",
        "_rocm_sdk_libraries",
        "_rocm_sdk_devel",
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