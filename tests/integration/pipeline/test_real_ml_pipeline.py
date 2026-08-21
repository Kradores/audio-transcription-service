from __future__ import annotations

import sqlite3
import wave
from collections.abc import AsyncIterator, Callable
from pathlib import Path

import numpy as np
import pytest

from app.audio.contracts import AudioFormat, AudioFrame
from app.audio.normalizer import AudioNormalizerImpl
from app.audio.resampler import SoXRResamplerFactory
from app.composition import (
    create_speech_assembler,
    create_transcription_executor,
    create_vad,
)
from app.core.config.constants import DEFAULT_CONFIGURATION_PATH
from app.core.config.loader import ConfigurationLoader
from app.services.speech_pipeline import SpeechPipeline
from app.transcription.contracts import AudioSource

FIXTURE_PATH = Path(__file__).parents[2] / "fixtures" / "audio" / "english_speech.wav"


class FixtureAudioCapture:
    """Replay a complete WAV fixture through the AudioCapture contract."""

    def __init__(self, frame: AudioFrame) -> None:
        self._frame = frame
        self._discontinuity_handler: Callable[[], None] | None = None

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def frames(self) -> AsyncIterator[AudioFrame]:
        yield self._frame

    def set_discontinuity_handler(
        self,
        handler: Callable[[], None],
    ) -> None:
        self._discontinuity_handler = handler


def _read_wav(path: Path) -> AudioFrame:
    with wave.open(str(path), "rb") as wav:
        sample_rate = wav.getframerate()
        channels = wav.getnchannels()
        sample_width = wav.getsampwidth()
        frame_count = wav.getnframes()
        audio_bytes = wav.readframes(frame_count)

    assert sample_width == 2

    samples = np.frombuffer(audio_bytes, dtype=np.int16)
    audio = samples.reshape(-1, channels)

    return AudioFrame(
        audio=audio,
        timestamp=0.0,
        format=AudioFormat(
            sample_rate=sample_rate,
            channels=channels,
            sample_type="int16",
        ),
    )


@pytest.mark.slow_integration
@pytest.mark.timeout(120)
@pytest.mark.anyio
async def test_real_ml_pipeline_transcribes_and_persists_audio_fixture() -> None:
    # Arrange
    settings = ConfigurationLoader(DEFAULT_CONFIGURATION_PATH).load()

    frame = _read_wav(FIXTURE_PATH)
    capture = FixtureAudioCapture(frame)

    normalizer = AudioNormalizerImpl(
        settings=settings.audio.processing,
        resampler_factory=SoXRResamplerFactory(),
    )

    vad = create_vad(settings)
    if vad is None:
        raise AssertionError("VAD must be enabled for this integration test")

    assembler = create_speech_assembler(settings.audio.segmentation)

    database = sqlite3.connect(":memory:")

    transcription_executor = create_transcription_executor(
        database=database,
        settings=settings,
    )

    pipeline = SpeechPipeline(
        source=AudioSource.SYSTEM_AUDIO,
        capture=capture,
        normalizer=normalizer,
        vad=vad,
        assembler=assembler,
        transcription_executor=transcription_executor,
    )

    # Act
    await transcription_executor.start()

    await pipeline.start()
    await pipeline.wait()
    await pipeline.stop()

    await transcription_executor.stop()

    # Assert
    rows = database.execute(
        """
        SELECT
            source,
            start_time,
            end_time,
            language,
            text
        FROM transcripts
        ORDER BY id
        """,
    ).fetchall()

    database.close()

    assert rows
    assert all(row[3] == "en" for row in rows)
    assert all(row[4].strip() for row in rows)
    assert all(row[2] >= row[1] for row in rows)
    assert all(row[0] == AudioSource.SYSTEM_AUDIO for row in rows)
