# Audio Transcription Service

A local Windows speech-to-text application that transcribes both sides of a conversation: system audio and microphone input.

Audio is captured and processed locally, speech is detected with Silero VAD, transcribed with Faster-Whisper / CTranslate2, and persisted to SQLite. The Windows controller provides Start/Stop controls together with access to logs, configuration, transcript data, diagnostics, and support bundles.

## Download

Download the latest Windows installers from **[GitHub Releases](https://github.com/Kradores/audio-transcription-service/releases/latest)**.

Choose the installer that matches the machine:

| Profile | Installer | Use when |
| --- | --- | --- |
| CPU | `AudioTranscriptionService-Setup-<version>.exe` | Recommended if you are unsure which version to install. |
| NVIDIA | `AudioTranscriptionService-Nvidia-Setup-<version>.exe` | The machine has a compatible NVIDIA GPU. The required CUDA runtime is packaged with the application. |
| AMD | `AudioTranscriptionService-Amd-Setup-<version>.exe` | The machine has supported AMD gfx1031-class hardware. Currently validated on AMD Radeon RX 6800M. |

The AMD distribution currently targets `gfx1031`; other AMD architectures are not assumed to be compatible. Independent clean-machine validation on a second compatible AMD computer is still deferred.

Each release also includes `SHA256SUMS.txt` for installer integrity verification.

## Features

- Captures Windows system audio through WASAPI loopback.
- Captures the default microphone independently.
- Automatically follows and recovers from Windows audio-device changes.
- Uses Silero VAD and speech-segment aggregation before transcription.
- Supports automatic, fixed, and per-source adaptive language selection.
- Runs Faster-Whisper locally through CPU, NVIDIA, or supported AMD runtimes.
- Stores completed transcripts in SQLite.
- Provides persistent logs, runtime diagnostics, and privacy-aware support bundles.

## Install and use

The current packaged distributions target Windows x86_64.

After downloading the appropriate installer from GitHub Releases, run it and launch **Audio Transcription Service** from the Start Menu.

Use **Start** to begin transcription and **Stop** to finish the current session gracefully.

Mutable application data is stored under:

```text
%LOCALAPPDATA%\AudioTranscriptionService\
    config\
    data\
    logs\
    diagnostics\
    support\
```

Configuration, transcripts, logs, diagnostics, and support bundles are preserved when the application binaries are upgraded or uninstalled.

## Development

The project uses Python 3.14 and `uv`.

```powershell
git clone https://github.com/Kradores/audio-transcription-service.git
cd audio-transcription-service
uv sync
```

Run the development controller with:

```powershell
uv run python -m app.controller.main
```

More detailed setup, runtime-specific preparation, and Windows packaging instructions are in [`docs/development.md`](docs/development.md) and [`docs/deployment.md`](docs/deployment.md).

## Test

Run the repository quality gate from the project root:

```powershell
uv run ruff format .
uv run ruff check .
uv run mypy .
uv run pytest -q
```

The test suite contains unit, integration, real-ML, and hardware-specific coverage. Some hardware integration tests require compatible Windows audio hardware or accelerator runtimes.

See [`docs/testing.md`](docs/testing.md) for the testing strategy and acceptance-test details.

## Documentation

Detailed project documentation lives in [`docs/`](docs/), including architecture, API contracts, development, testing, deployment, observability, roadmap, and architectural decision records.

## Status

CPU, NVIDIA, and AMD gfx1031 Windows packaged distributions and installers are implemented. NVIDIA has completed external-machine acceptance. AMD packaged and installed acceptance has been completed on Radeon RX 6800M hardware; independent clean-machine AMD acceptance on a second compatible machine is currently deferred.
