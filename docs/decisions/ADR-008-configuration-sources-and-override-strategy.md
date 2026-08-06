# ADR-008: Configuration Sources and Override Strategy

## Status
Accepted

## Context
Instead of using:
```
config.yaml
```
plus lots of environment variables...

...I'd like us to follow a layered configuration model.
```
Defaults
      ↓
config.yaml
      ↓
Environment Variables
      ↓
Command-line arguments (future)
```

For example:
```
audio:
  sample_rate: 16000
```
can always be overridden by
```
AUDIO_SAMPLE_RATE=48000
```

This is extremely useful later if you:
- run inside Docker
- deploy on another machine
- benchmark different models
- create multiple environments (dev/test/prod)

We don't need CLI overrides yet, but I want to design for them.
