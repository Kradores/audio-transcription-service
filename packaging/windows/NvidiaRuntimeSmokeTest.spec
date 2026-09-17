from pathlib import Path


repository_root = Path(SPECPATH).resolve().parents[1]

runtime_directory = (
    repository_root
    / "build"
    / "nvidia-smoke"
    / "runtime"
)

fixture_path = (
    repository_root
    / "tests"
    / "fixtures"
    / "audio"
    / "english_speech.wav"
)

entry_point = (
    repository_root
    / "scripts"
    / "nvidia"
    / "runtime_smoke_test.py"
)


if not runtime_directory.is_dir():
    raise RuntimeError(
        "NVIDIA runtime staging directory does not exist: "
        f"{runtime_directory}"
    )


runtime_binaries = [
    (
        str(path),
        "nvidia-runtime",
    )
    for path in sorted(
        runtime_directory.glob("*.dll")
    )
]


analysis = Analysis(
    [str(entry_point)],
    pathex=[str(repository_root)],
    binaries=runtime_binaries,
    datas=[
        (
            str(
                runtime_directory
                / "manifest.json"
            ),
            "nvidia-runtime",
        ),
        (
            str(fixture_path),
            "fixtures",
        ),
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "torch",
        "silero_vad",
        "pyaudiowpatch",
        "pycaw",
    ],
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
    name="NvidiaRuntimeSmokeTest",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
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
    name="NvidiaRuntimeSmokeTest",
)