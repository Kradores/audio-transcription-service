from __future__ import annotations

import hashlib
import json
import wave
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

from app.audio.contracts import AudioFormat, SpeechSegment
from app.core.config.models import SlowInferenceCaptureSettings
from app.transcription.slow_inference_capture import (
    SlowInferenceCapture,
    SlowInferenceDiagnostics,
)


def create_segment() -> SpeechSegment:
    sample_rate = 16_000

    audio = np.array(
        [
            [-1.0],
            [-0.5],
            [0.0],
            [0.5],
            [1.0],
        ],
        dtype=np.float32,
    )

    return SpeechSegment(
        audio=audio,
        timestamp=12.5,
        duration=audio.shape[0] / sample_rate,
        format=AudioFormat(
            sample_rate=sample_rate,
            channels=1,
            sample_type="float32",
        ),
    )


def create_diagnostics(
    *,
    inference_duration_seconds: float,
) -> SlowInferenceDiagnostics:
    return SlowInferenceDiagnostics(
        inference_duration_seconds=inference_duration_seconds,
        model_setup_duration_seconds=0.1,
        decoding_duration_seconds=inference_duration_seconds - 0.1,
        selected_language="ro",
        result_language="ro",
        result_confidence=None,
        output_segments=1,
        output_characters=5,
    )


@pytest.mark.parametrize(
    ("enabled", "inference_duration_seconds"),
    [
        (False, 10.0),
        (True, 4.999),
    ],
)
def test_capture_skips_when_not_eligible(
    tmp_path: Path,
    enabled: bool,
    inference_duration_seconds: float,
) -> None:
    capture_root = tmp_path / "captures"

    capture = SlowInferenceCapture(
        SlowInferenceCaptureSettings(
            enabled=enabled,
            threshold_seconds=5.0,
            directory=capture_root,
        )
    )

    result = capture.capture_if_slow(
        segment=create_segment(),
        diagnostics=create_diagnostics(
            inference_duration_seconds=inference_duration_seconds,
        ),
    )

    assert result is None
    assert not capture_root.exists()


def test_capture_saves_exact_audio_wav_and_metadata(
    tmp_path: Path,
) -> None:
    segment = create_segment()

    capture = SlowInferenceCapture(
        SlowInferenceCaptureSettings(
            enabled=True,
            threshold_seconds=5.0,
            directory=tmp_path / "captures",
        )
    )

    result = capture.capture_if_slow(
        segment=segment,
        diagnostics=create_diagnostics(
            inference_duration_seconds=5.0,
        ),
    )

    assert result is not None

    stored_audio = np.load(
        result / "audio.npy",
        allow_pickle=False,
    )

    np.testing.assert_array_equal(
        stored_audio,
        segment.audio[:, 0],
    )

    metadata = json.loads(
        (result / "metadata.json").read_text(
            encoding="utf-8",
        )
    )

    expected_sha256 = hashlib.sha256(
        np.ascontiguousarray(
            segment.audio[:, 0],
            dtype=np.float32,
        ).tobytes(order="C"),
    ).hexdigest()

    assert metadata["schema_version"] == 1
    assert metadata["segment_timestamp"] == segment.timestamp
    assert metadata["segment_duration"] == segment.duration
    assert metadata["sample_rate"] == segment.format.sample_rate
    assert metadata["sample_count"] == segment.audio.shape[0]
    assert metadata["dtype"] == "float32"
    assert metadata["audio_sha256"] == expected_sha256
    assert metadata["selected_language"] == "ro"
    assert metadata["inference_duration_seconds"] == 5.0

    with wave.open(
        str(result / "audio.wav"),
        "rb",
    ) as wav:
        assert wav.getnchannels() == 1
        assert wav.getsampwidth() == 2
        assert wav.getframerate() == 16_000
        assert wav.getnframes() == segment.audio.shape[0]


def test_capture_failure_does_not_escape_into_transcription_pipeline(
    tmp_path: Path,
) -> None:
    capture = SlowInferenceCapture(
        SlowInferenceCaptureSettings(
            enabled=True,
            threshold_seconds=5.0,
            directory=tmp_path / "captures",
        )
    )

    with patch(
        "app.transcription.slow_inference_capture.np.save",
        side_effect=OSError("disk full"),
    ):
        result = capture.capture_if_slow(
            segment=create_segment(),
            diagnostics=create_diagnostics(
                inference_duration_seconds=10.0,
            ),
        )

    assert result is None
