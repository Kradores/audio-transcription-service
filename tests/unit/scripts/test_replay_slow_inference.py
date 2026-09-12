from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

from scripts.replay_slow_inference import (
    CaptureMetadata,
    load_capture,
    resolve_language,
)


def write_capture(
    directory: Path,
    *,
    audio_sha256: str | None = None,
) -> np.ndarray:
    directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    audio = np.array(
        [
            -0.5,
            0.0,
            0.5,
        ],
        dtype=np.float32,
    )

    np.save(
        directory / "audio.npy",
        audio,
        allow_pickle=False,
    )

    actual_sha256 = hashlib.sha256(
        audio.tobytes(order="C"),
    ).hexdigest()

    metadata = {
        "selected_language": "ro",
        "sample_rate": 16_000,
        "sample_count": audio.shape[0],
        "dtype": "float32",
        "audio_sha256": audio_sha256 or actual_sha256,
        "inference_duration_seconds": 12.5,
    }

    (directory / "metadata.json").write_text(
        json.dumps(metadata),
        encoding="utf-8",
    )

    return audio


def test_load_capture_returns_exact_saved_audio(
    tmp_path: Path,
) -> None:
    expected_audio = write_capture(tmp_path)

    audio, metadata = load_capture(tmp_path)

    np.testing.assert_array_equal(
        audio,
        expected_audio,
    )

    assert metadata.selected_language == "ro"
    assert metadata.sample_rate == 16_000
    assert metadata.sample_count == 3
    assert metadata.dtype == "float32"
    assert metadata.inference_duration_seconds == 12.5


def test_load_capture_rejects_corrupted_audio(
    tmp_path: Path,
) -> None:
    write_capture(
        tmp_path,
        audio_sha256="invalid",
    )

    with pytest.raises(
        ValueError,
        match="SHA-256",
    ):
        load_capture(tmp_path)


@pytest.mark.parametrize(
    ("requested_language", "expected_language"),
    [
        ("original", "ro"),
        ("auto", None),
        ("en", "en"),
    ],
)
def test_resolve_language(
    requested_language: str,
    expected_language: str | None,
) -> None:
    metadata = CaptureMetadata(
        selected_language="ro",
        sample_rate=16_000,
        sample_count=100,
        dtype="float32",
        audio_sha256="abc",
        inference_duration_seconds=10.0,
    )

    assert (
        resolve_language(
            requested_language,
            metadata,
        )
        == expected_language
    )
