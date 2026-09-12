from __future__ import annotations

import hashlib
import json
import logging
import wave
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import numpy as np

from app.audio.contracts import SpeechSegment
from app.core.config.models import SlowInferenceCaptureSettings

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SlowInferenceDiagnostics:
    inference_duration_seconds: float
    model_setup_duration_seconds: float
    decoding_duration_seconds: float
    selected_language: str | None
    result_language: str
    result_confidence: float | None
    output_segments: int
    output_characters: int


class SlowInferenceCapture:
    """Preserve model input and metadata for unusually slow transcriptions."""

    def __init__(
        self,
        settings: SlowInferenceCaptureSettings,
    ) -> None:
        self._settings = settings

    def capture_if_slow(
        self,
        *,
        segment: SpeechSegment,
        diagnostics: SlowInferenceDiagnostics,
    ) -> Path | None:
        if not self._settings.enabled:
            return None

        if diagnostics.inference_duration_seconds < self._settings.threshold_seconds:
            return None

        audio = np.ascontiguousarray(
            segment.audio[:, 0],
            dtype=np.float32,
        )

        captured_at = datetime.now(UTC)
        capture_name = f"{captured_at.strftime('%Y%m%dT%H%M%S.%fZ')}-{uuid4().hex[:8]}"
        capture_directory = self._settings.directory / capture_name

        try:
            capture_directory.mkdir(
                parents=True,
                exist_ok=False,
            )

            np.save(
                capture_directory / "audio.npy",
                audio,
                allow_pickle=False,
            )

            self._write_wav(
                path=capture_directory / "audio.wav",
                audio=audio,
                sample_rate=segment.format.sample_rate,
            )

            audio_sha256 = hashlib.sha256(
                audio.tobytes(order="C"),
            ).hexdigest()

            metadata = {
                "schema_version": 1,
                "captured_at_utc": captured_at.isoformat(),
                "segment_timestamp": segment.timestamp,
                "segment_duration": segment.duration,
                "sample_rate": segment.format.sample_rate,
                "sample_count": int(audio.shape[0]),
                "dtype": str(audio.dtype),
                "audio_sha256": audio_sha256,
                **asdict(diagnostics),
            }

            with (capture_directory / "metadata.json").open(
                "w",
                encoding="utf-8",
            ) as file:
                json.dump(
                    metadata,
                    file,
                    indent=2,
                    ensure_ascii=False,
                )

        except OSError, wave.Error:
            logger.exception(
                "failed to capture slow inference audio "
                "start=%.3f duration=%.3f inference_duration=%.3f",
                segment.timestamp,
                segment.duration,
                diagnostics.inference_duration_seconds,
            )
            return None

        logger.warning(
            "slow inference audio captured "
            "path=%s start=%.3f duration=%.3f "
            "inference_duration=%.3f decoding_duration=%.3f "
            "language_selection=%s",
            capture_directory,
            segment.timestamp,
            segment.duration,
            diagnostics.inference_duration_seconds,
            diagnostics.decoding_duration_seconds,
            diagnostics.selected_language or "auto",
        )

        return capture_directory

    @staticmethod
    def _write_wav(
        *,
        path: Path,
        audio: np.ndarray,
        sample_rate: int,
    ) -> None:
        pcm16 = (np.clip(audio, -1.0, 1.0) * np.iinfo(np.int16).max).astype(np.int16)

        with wave.open(str(path), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(sample_rate)
            wav.writeframes(pcm16.tobytes())
