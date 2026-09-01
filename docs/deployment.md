## runtime concerns:
Windows required
WASAPI available
default render device required
device loss is recoverable
device changes are followed automatically
application remains alive during recovery

## SQLite

Transcript persistence uses a local SQLite database.

The database location is configured through `database.path`.

The configured database directory must be writable by the application.
The application creates the configured parent directory when it does not
already exist.

No external database service is required.

## AMD GPU transcription runtime

AMD acceleration is optional and applies specifically to Faster-Whisper
transcription.

Silero VAD remains CPU-backed.

The currently validated AMD deployment target is:

```text
Windows x86_64
Python 3.14.6
AMD Radeon RX 6800M
gfx1031
TheRock 10.1.0a20260829 packages
custom CTranslate2 4.8.1 wheel
Intel oneAPI OpenMP 2026.1 runtime
```

The custom CTranslate2 wheel contains the validated:

```text
ctranslate2.dll
libiomp5md.dll
```

The production runtime must initialize TheRock before importing
CTranslate2/Faster-Whisper.

An explicitly configured:

```yaml
whisper:
  runtime: therock
```

requires the AMD backend.

Missing or broken AMD native dependencies are startup failures.

The application does not silently fall back to CPU.

The validated AMD transcription settings are:

```yaml
transcription:
  worker_count: 1

whisper:
  runtime: therock
  device: cuda
  compute_type: float16
```

The ordinary CPU deployment remains independent and does not require TheRock,
Intel OpenMP, or the custom HIP-enabled CTranslate2 artifact.

Support for GPU architectures other than `gfx1031` requires a separately built
and validated artifact.

Native AMD build preparation is performed ahead of runtime through
`scripts/amd/prepare.ps1`.

The application must not compile CTranslate2 opportunistically during normal
startup.