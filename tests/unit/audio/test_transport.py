import asyncio

import pytest

from app.audio.contracts import AudioFrame
from app.audio.transport import AudioFrameTransport
from tests.unit.audio.helpers import create_frame


def test_transport_rejects_invalid_capacity() -> None:
    with pytest.raises(ValueError, match="capacity must be positive"):
        AudioFrameTransport(capacity=0)


def test_transport_accepts_frame() -> None:
    transport = AudioFrameTransport(capacity=1)
    frame = create_frame(1.0)

    assert transport.submit(frame) is True


def test_transport_preserves_fifo_order() -> None:
    transport = AudioFrameTransport(capacity=3)

    frames = [
        create_frame(1.0),
        create_frame(2.0),
        create_frame(3.0),
    ]

    for frame in frames:
        assert transport.submit(frame) is True

    async def consume() -> list[AudioFrame]:
        consumed: list[AudioFrame] = []

        async for frame in transport.frames():
            consumed.append(frame)

            if len(consumed) == len(frames):
                await transport.close()

        return consumed

    consumed = asyncio.run(consume())

    assert consumed == frames


def test_transport_drops_frame_when_full() -> None:
    transport = AudioFrameTransport(capacity=1)

    assert transport.submit(create_frame(1.0)) is True
    assert transport.submit(create_frame(2.0)) is False

    assert transport.frames_dropped == 1


def test_transport_does_not_drop_when_capacity_available() -> None:
    transport = AudioFrameTransport(capacity=2)

    assert transport.submit(create_frame(1.0)) is True
    assert transport.submit(create_frame(2.0)) is True

    assert transport.frames_dropped == 0


def test_transport_rejects_frames_after_close() -> None:
    transport = AudioFrameTransport(capacity=1)

    asyncio.run(transport.close())

    assert transport.submit(create_frame(1.0)) is False
    assert transport.frames_dropped == 0


def test_close_discards_queued_frames() -> None:
    transport = AudioFrameTransport(capacity=2)

    assert transport.submit(create_frame(1.0)) is True
    assert transport.submit(create_frame(2.0)) is True

    asyncio.run(transport.close())

    async def consume() -> list[AudioFrame]:
        return [frame async for frame in transport.frames()]

    assert asyncio.run(consume()) == []


def test_close_is_idempotent() -> None:
    transport = AudioFrameTransport(capacity=1)

    asyncio.run(transport.close())
    asyncio.run(transport.close())

    assert transport.submit(create_frame(1.0)) is False


@pytest.mark.anyio
async def test_consumer_waits_for_frame() -> None:
    transport = AudioFrameTransport(capacity=1)
    consumed: list[AudioFrame] = []
    consumed_event = asyncio.Event()

    async def consume() -> None:
        async for frame in transport.frames():
            consumed.append(frame)
            consumed_event.set()

    consumer = asyncio.create_task(consume())

    try:
        await asyncio.sleep(0)
        assert consumed == []

        frame = create_frame(1.0)

        assert transport.submit(frame) is True
        await asyncio.wait_for(consumed_event.wait(), timeout=1.0)

        assert consumed == [frame]

    finally:
        await transport.close()
        await consumer
