from __future__ import annotations

from app.core.runtime_paths import create_development_runtime_paths

DEFAULT_CONFIGURATION_PATH = create_development_runtime_paths().config_path
PROCESSING_FRAME_DURATION_SECONDS = 0.020
PROCESSING_FRAME_DURATION_MS = int(PROCESSING_FRAME_DURATION_SECONDS * 1000)
