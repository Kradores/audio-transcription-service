# AMD / TheRock Transcription Tooling

This directory contains the reproducible Windows AMD GPU build, packaging,
runtime-validation, and application-preparation tooling for Faster-Whisper.

## Start here

For normal AMD development setup, run only:

```powershell
.\scripts\amd\prepare.ps1
```

Do not manually run every script in this directory.

`prepare.ps1` is the primary developer entry point and executes the required
stages in the correct order.

For a clean native rebuild:

```powershell
.\scripts\amd\prepare.ps1 -Clean
```

For a clean rebuild including the sustained teardown regression:

```powershell
.\scripts\amd\prepare.ps1 `
    -Clean `
    -RunLongValidation
```

The sustained validation defaults to 20 minutes and is intentionally not part
of the normal setup path.

## What the entry point does

The preparation flow is:

```text
prepare.ps1
    │
    ├── test_prerequisites.ps1
    │
    ├── prepare_ctranslate2_build.ps1
    │
    ├── build_ctranslate2.ps1
    │       └── configure_ctranslate2.ps1
    │
    ├── build_wheel.ps1
    │
    ├── optional:
    │       test_long_runtime.ps1
    │
    └── prepare_application_runtime.ps1
            └── test_runtime.ps1
                    └── runtime_smoke_test.py
```

At the end, the isolated runtime contains:

```text
CPU:
    Silero VAD
    torch + torchaudio CPU builds

AMD GPU:
    Faster-Whisper
        ↓
    custom CTranslate2
        ↓
    TheRock / HIP
        ↓
    supported AMD GPU
```

The normal CPU `.venv` is not modified.

## Script responsibilities

| Script | Normal developer entry point? | Responsibility |
| --- | --- | --- |
| `prepare.ps1` | **Yes** | Complete AMD build, packaging, smoke validation, and application-runtime preparation |
| `test_prerequisites.ps1` | No | Validate pinned native/build prerequisites |
| `prepare_ctranslate2_build.ps1` | No | Prepare exact CTranslate2 source revision, workspace, and staged Intel OpenMP files |
| `configure_ctranslate2.ps1` | No | Configure the HIP + Intel OpenMP CMake build |
| `build_ctranslate2.ps1` | No | Build/install and inspect the native CTranslate2 DLL |
| `build_wheel.ps1` | No | Build the custom Python wheel containing the validated native runtime |
| `test_runtime.ps1` | No | Create a fresh isolated Faster-Whisper runtime and run the GPU smoke test |
| `prepare_application_runtime.ps1` | No | Extend the isolated runtime with the complete application dependencies and revalidate CPU Silero + AMD CTranslate2 |
| `test_long_runtime.ps1` | Optional | Sustained GPU inference and teardown regression |
| `runtime_smoke_test.py` | No | Python implementation used by `test_runtime.ps1` |
| `runtime_long_test.py` | No | Python workload used by `test_long_runtime.ps1` |
| `toolchain.json` | No | Pinned native toolchain/runtime contract and reference artifacts |
| `runtime-requirements.txt` | No | Pinned Faster-Whisper runtime dependencies excluding CTranslate2/TheRock |
| `application-runtime-requirements.txt` | No | Pinned application dependencies added after the AMD transcription runtime is validated |

Individual stage scripts remain directly executable for debugging or when
working specifically on that stage.

They are not the normal setup interface.

## Running the application

After `prepare.ps1` succeeds:

```powershell
$amdPython = Join-Path `
    $env:TEMP `
    "audio-transcription-service-amd\runtime-test-venv\Scripts\python.exe"

& $amdPython -m app
```

The AMD configuration uses:

```yaml
transcription:
  worker_count: 1

whisper:
  runtime: therock
  model: small
  device: cuda
  compute_type: float16
```

`cuda` is intentionally used as the CTranslate2 device identifier for the HIP
backend.

There is no application-level `rocm` device value.

## Environment isolation

Do not use `uv sync` against the isolated AMD runtime.

Do not use an ambiguous `uv run` command when validating the AMD runtime.

The custom CTranslate2 wheel is part of the validated native runtime and must
not be silently replaced by dependency resolution.

Use the explicit Python interpreter produced by the scripts.

The project's normal CPU `.venv` remains independent.