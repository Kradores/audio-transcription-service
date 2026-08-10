from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest

from app.audio.contracts import AudioFrame
from app.audio.transport import AudioFrameTransport
from tests.unit.audio.helpers import consume_one, consume_stream, create_frame


class FakeAudioCapture:
    """Minimal test double implementing AudioCapture."""

    def __init__(self) -> None:
        self._transport = AudioFrameTransport(capacity=4)
        self._started = False

    def start(self) -> None:
        if self._started:
            return

        self._started = True

    def frames(self) -> AsyncIterator[AudioFrame]:
        return self._transport.frames()

    async def stop(self) -> None:
        if not self._started:
            return

        self._started = False
        await self._transport.close()

    async def submit(self, frame: AudioFrame) -> bool:
        return self._transport.submit(frame)


@pytest.mark.anyio
async def test_capture_streams_frames() -> None:
    capture = FakeAudioCapture()
    capture.start()

    frame = create_frame(1.0)
    consumer = asyncio.create_task(consume_one(capture))

    try:
        assert await capture.submit(frame) is True

        consumed = await asyncio.wait_for(consumer, timeout=1.0)

        assert consumed == frame
    finally:
        await capture.stop()
        await consumer


@pytest.mark.anyio
async def test_stop_terminates_capture_stream() -> None:
    capture = FakeAudioCapture()
    capture.start()

    consumer = asyncio.create_task(consume_stream(capture))

    await capture.stop()

    await asyncio.wait_for(consumer, timeout=1.0)
