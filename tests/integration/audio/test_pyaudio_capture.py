from __future__ import annotations

import asyncio
import winsound

import pytest

from app.audio.capture import PyAudioCapture
from app.composition import create_capture
from app.core.config.constants import DEFAULT_CONFIGURATION_PATH
from app.core.config.loader import ConfigurationLoader

CAPTURE_DURATION_SECONDS = 2.0


@pytest.mark.hardware_integration
@pytest.mark.timeout(30)
@pytest.mark.anyio
async def test_real_pyaudio_capture_receives_wasapi_loopback_frames() -> None:
    # Arrange
    settings = ConfigurationLoader(DEFAULT_CONFIGURATION_PATH).load()
    capture = create_capture(settings.audio.capture.queue_capacity)

    frames = []

    # Act
    await capture.start()

    try:

        async def collect_frames() -> None:
            async for frame in capture.frames():
                frames.append(frame)

        collector = asyncio.create_task(collect_frames())
        await asyncio.to_thread(winsound.Beep, 37, int(CAPTURE_DURATION_SECONDS * 10))

        await asyncio.sleep(CAPTURE_DURATION_SECONDS)
    finally:
        await capture.stop()

    await collector

    # Assert
    assert isinstance(capture, PyAudioCapture)
    assert frames

    timestamps = [frame.timestamp for frame in frames]

    assert timestamps[0] >= 0.0
    assert timestamps == sorted(timestamps)

    for frame in frames:
        assert frame.format.sample_type == "int16"
        assert frame.audio.dtype.name == "int16"
        assert frame.audio.ndim == 2
        assert frame.audio.shape[1] == frame.format.channels
        assert frame.audio.shape[0] > 0

    assert timestamps[-1] > timestamps[0]
