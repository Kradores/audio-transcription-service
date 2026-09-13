from __future__ import annotations

import hashlib
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from scripts.replay_slow_inference import (
    CaptureMetadata,
    ReplayDecodingOverrides,
    describe_overrides,
    load_capture,
    resolve_language,
    run_replay_once,
    transcribe_with_overrides,
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


def test_decoding_overrides_accept_defaults() -> None:
    overrides = ReplayDecodingOverrides()

    overrides.validate()


@pytest.mark.parametrize(
    "temperature",
    [
        -0.1,
        -1.0,
    ],
)
def test_decoding_overrides_reject_negative_temperature(
    temperature: float,
) -> None:
    overrides = ReplayDecodingOverrides(
        temperature=temperature,
    )

    with pytest.raises(
        ValueError,
        match="temperature",
    ):
        overrides.validate()


@pytest.mark.parametrize(
    "max_new_tokens",
    [
        0,
        -1,
    ],
)
def test_decoding_overrides_reject_non_positive_max_new_tokens(
    max_new_tokens: int,
) -> None:
    overrides = ReplayDecodingOverrides(
        max_new_tokens=max_new_tokens,
    )

    with pytest.raises(
        ValueError,
        match="max-new-tokens",
    ):
        overrides.validate()


def test_transcribe_without_overrides_preserves_model_defaults() -> None:
    model = MagicMock()
    audio = np.zeros(16_000, dtype=np.float32)

    transcribe_with_overrides(
        model=model,
        audio=audio,
        language="ro",
        overrides=ReplayDecodingOverrides(),
    )

    model.transcribe.assert_called_once_with(
        audio,
        language="ro",
    )


def test_transcribe_passes_temperature_override() -> None:
    model = MagicMock()
    audio = np.zeros(16_000, dtype=np.float32)

    transcribe_with_overrides(
        model=model,
        audio=audio,
        language=None,
        overrides=ReplayDecodingOverrides(
            temperature=0.0,
        ),
    )

    model.transcribe.assert_called_once_with(
        audio,
        language=None,
        temperature=0.0,
    )


def test_transcribe_passes_max_new_tokens_override() -> None:
    model = MagicMock()
    audio = np.zeros(16_000, dtype=np.float32)

    transcribe_with_overrides(
        model=model,
        audio=audio,
        language=None,
        overrides=ReplayDecodingOverrides(
            max_new_tokens=64,
        ),
    )

    model.transcribe.assert_called_once_with(
        audio,
        language=None,
        max_new_tokens=64,
    )


def test_transcribe_passes_both_decoding_overrides() -> None:
    model = MagicMock()
    audio = np.zeros(16_000, dtype=np.float32)

    transcribe_with_overrides(
        model=model,
        audio=audio,
        language="en",
        overrides=ReplayDecodingOverrides(
            temperature=0.0,
            max_new_tokens=32,
        ),
    )

    model.transcribe.assert_called_once_with(
        audio,
        language="en",
        temperature=0.0,
        max_new_tokens=32,
    )


def test_describe_overrides_identifies_library_defaults() -> None:
    result = describe_overrides(
        ReplayDecodingOverrides(),
    )

    assert result == ("temperature=default-fallback max_new_tokens=model-default")


def test_run_replay_once_reports_output_token_count() -> None:
    first_segment = MagicMock()
    first_segment.text = "Hello"
    first_segment.tokens = [1, 2, 3]

    second_segment = MagicMock()
    second_segment.text = "world"
    second_segment.tokens = [4, 5]

    info = MagicMock()
    info.language = "en"
    info.language_probability = 0.95

    model = MagicMock()
    model.transcribe.return_value = (
        [first_segment, second_segment],
        info,
    )

    audio = np.zeros(
        16_000,
        dtype=np.float32,
    )

    with patch(
        "scripts.replay_slow_inference.time.perf_counter",
        side_effect=[
            10.0,
            10.2,
            11.0,
        ],
    ):
        result = run_replay_once(
            model=model,
            audio=audio,
            language=None,
            overrides=ReplayDecodingOverrides(),
        )

    assert result.total_seconds == pytest.approx(1.0)
    assert result.setup_seconds == pytest.approx(0.2)
    assert result.decoding_seconds == pytest.approx(0.8)
    assert result.output_segments == 2
    assert result.output_tokens == 5
    assert result.text == "Hello world"
