import asyncio

import numpy as np

from app.audio.contracts import AudioFormat, AudioFrame
from app.audio.protocols import AudioCapture

AUDIO_FORMAT = AudioFormat(
    sample_rate=48_000,
    channels=1,
    sample_type="int16",
)


def create_frame(timestamp: float) -> AudioFrame:
    return AudioFrame(
        audio=np.zeros((480, 1), dtype=np.int16),
        timestamp=timestamp,
        format=AUDIO_FORMAT,
    )


async def consume_one(capture: AudioCapture) -> AudioFrame:
    async for frame in capture.frames():
        return frame

    raise AssertionError("Capture stream ended before a frame was received")


async def consume_stream(capture: AudioCapture) -> list[AudioFrame]:
    frames: list[AudioFrame] = []

    async for frame in capture.frames():
        frames.append(frame)

    return frames


async def wait_for_consumed_frame(
    consumed: list[AudioFrame],
) -> None:
    while not consumed:
        await asyncio.sleep(0)
