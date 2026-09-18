from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files


repository_root = Path(SPECPATH).resolve().parents[1]

entry_point = repository_root / "app" / "controller" / "windows_main.py"


distribution_metadata_path = (
    repository_root / "build" / "distribution-metadata" / "cpu" / "distribution-metadata.json"
)

if not distribution_metadata_path.is_file():
    raise RuntimeError(f"CPU distribution metadata does not exist: {distribution_metadata_path}")


analysis = Analysis(
    [str(entry_point)],
    pathex=[str(repository_root)],
    binaries=[],
    datas=(
        collect_data_files("silero_vad")
        + [
            (
                str(distribution_metadata_path),
                ".",
            )
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


pyz = PYZ(analysis.pure)


exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="AudioTranscriptionService",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
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
    upx=True,
    upx_exclude=[],
    name="AudioTranscriptionService",
)
