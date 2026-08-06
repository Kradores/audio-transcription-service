# High-Level Architecture

```text
Windows System Audio
        │
        ▼
Audio Capture (WASAPI Loopback)
        │
        ▼
Voice Activity Detection (Silero VAD)
        │
Speech Detected?
        │
       Yes
        │
        ▼
Collect 2–5 Seconds of Audio
        │
        ▼
Faster-Whisper Small
        │
        ▼
Transcript
        │
        ▼
SQLite Database
```

# Project Structure
```
audio-transcription-service/
│
├── app/
│   ├── api/
│   │   ├── __init__.py
│   │   ├── health.py
│   │   └── status.py
│   │
│   ├── audio/
│   ├── transcription/
│   ├── vad/
│   ├── storage/
│   │
│   ├── core/
│   │   ├── __init__.py
│   │   ├── config.py
│   │   ├── logging.py
│   │   └── lifecycle.py
│   │
│   ├── models/
│   ├── services/
│   ├── utils/
│   │
│   ├── main.py
│   └── __init__.py
│
├── config/
│   └── config.yaml
│
├── docs/
│   ├── architecture.md
│   ├── roadmap.md
│   ├── testing.md
│   ├── observability.md
|   ├── engineering-principles.md
│   ├── development.md
│   └── decisions/
│
├── scripts/
│
├── tests/
│   ├── unit/
│   ├── integration/
│   └── resources/
│
├── .gitignore
├── pyproject.toml
├── README.md
└── LICENSE
```