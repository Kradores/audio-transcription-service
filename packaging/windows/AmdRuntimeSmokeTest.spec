from pathlib import Path


repository_root = Path(SPECPATH).resolve().parents[1]

runtime_directory = (
    repository_root
    / "build"
    / "amd-smoke"
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
    / "amd"
    / "runtime_smoke_test.py"
)


if not runtime_directory.is_dir():
    raise RuntimeError(
        "AMD runtime staging directory does not exist: "
        f"{runtime_directory}"
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
    datas=[
        *runtime_datas,
        (
            str(fixture_path),
            "fixtures",
        ),
    ],
    hiddenimports=[
        "_rocm_sdk_core",
        "_rocm_sdk_libraries",
        "_rocm_sdk_devel",
    ],
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
    name="AmdRuntimeSmokeTest",
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
    name="AmdRuntimeSmokeTest",
)