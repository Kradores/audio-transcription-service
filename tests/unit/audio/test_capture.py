from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, MagicMock

import numpy as np
import pyaudiowpatch
import pytest

from app.audio.capture import (
    PyAudioCapture,
    QueuedAudioCapture,
    WasapiAudioFrameFactory,
    WasapiLoopbackDevice,
)
from app.audio.contracts import AudioFormat, AudioFrame
from app.audio.transport import AudioFrameTransport
from tests.unit.audio.helpers import (
    consume_one,
    consume_stream,
    create_frame,
)


class FakeAudioCapture:
    """Minimal test double implementing AudioCapture."""

    def __init__(self) -> None:
        self._transport = AudioFrameTransport(capacity=4)
        self._started = False

    async def start(self) -> None:
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


recorded_delays: list[float] = []


async def immediate_sleep(delay: float) -> None:
    recorded_delays.append(delay)


@pytest.mark.anyio
async def test_capture_streams_frames() -> None:
    capture = FakeAudioCapture()
    await capture.start()

    frame = create_frame(1.0)
    consumer = asyncio.create_task(consume_one(capture))

    try:
        assert await capture.submit(frame) is True

        consumed = await asyncio.wait_for(consumer, timeout=1.0)

        assert consumed == frame
    finally:
        await capture.stop()
        await consumer


def test_wasapi_audio_frame_factory_creates_frame() -> None:
    audio_format = AudioFormat(
        sample_rate=44_100,
        channels=2,
        sample_type="int16",
    )
    factory = WasapiAudioFrameFactory(audio_format)

    samples = np.array(
        [
            [100, 200],
            [300, 400],
            [500, 600],
        ],
        dtype=np.int16,
    )

    frame = factory.create(
        in_data=samples.tobytes(),
        frame_count=3,
        time_info={"input_buffer_adc_time": 12.5},
    )

    assert frame.timestamp == 12.5
    assert frame.format == audio_format
    np.testing.assert_array_equal(frame.audio, samples)


def test_wasapi_audio_frame_factory_uses_callback_frame_count() -> None:
    audio_format = AudioFormat(
        sample_rate=44_100,
        channels=2,
        sample_type="int16",
    )
    factory = WasapiAudioFrameFactory(audio_format)

    samples = np.array(
        [
            [100, 200],
            [300, 400],
        ],
        dtype=np.int16,
    )

    frame = factory.create(
        in_data=samples.tobytes(),
        frame_count=2,
        time_info={"input_buffer_adc_time": 1.0},
    )

    assert frame.audio.shape == (2, 2)


@pytest.mark.anyio
async def test_start_uses_injected_device_provider() -> None:
    audio = MagicMock()
    stream = MagicMock()

    device = WasapiLoopbackDevice(
        index=42,
        name="Test Speakers [Loopback]",
        channels=2,
        sample_rate=48_000,
    )

    device_provider = MagicMock()
    device_provider.get_default.return_value = device

    transport = QueuedAudioCapture(max_queue_size=4)
    audio.open.return_value = stream

    capture = PyAudioCapture(
        audio=audio,
        device_provider=device_provider,
        transport=transport,
    )

    try:
        await capture.start()

        device_provider.get_default.assert_called_once_with()
        audio.get_default_wasapi_loopback.assert_not_called()
        audio.open.assert_called_once()
        stream.start_stream.assert_called_once_with()
    finally:
        await capture.stop()


@pytest.mark.anyio
async def test_start_enters_recovery_when_no_loopback_device_is_available() -> None:
    audio = MagicMock()
    device_provider = MagicMock()
    device_provider.get_default.side_effect = LookupError

    transport = QueuedAudioCapture(max_queue_size=4)

    capture = PyAudioCapture(
        audio=audio,
        device_provider=device_provider,
        transport=transport,
    )

    await capture.start()

    try:
        assert capture._lifecycle_task is not None
        assert capture._stream is None
    finally:
        await capture.stop()


@pytest.mark.anyio
async def test_start_opens_default_wasapi_loopback_stream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    audio = MagicMock()
    stream = MagicMock()

    device = WasapiLoopbackDevice(
        index=42,
        name="Test Speakers [Loopback]",
        channels=2,
        sample_rate=48_000.0,
    )

    audio.open.return_value = stream

    monkeypatch.setattr(
        "app.audio.capture.pyaudiowpatch.PyAudio",
        lambda: audio,
    )

    fake_device_provider = MagicMock()
    fake_device_provider.get_default.return_value = device

    fake_transport = MagicMock()
    fake_transport.start = AsyncMock()
    fake_transport.stop = AsyncMock()

    capture = PyAudioCapture(
        audio=audio,
        device_provider=fake_device_provider,
        transport=fake_transport,
    )

    try:
        await capture.start()
    finally:
        await capture.stop()

    fake_device_provider.get_default.assert_called_once_with()

    fake_transport.start.assert_awaited_once_with()
    fake_transport.stop.assert_awaited_once_with()

    audio.open.assert_called_once_with(
        rate=48_000,
        channels=2,
        format=pyaudiowpatch.paInt16,
        input=True,
        input_device_index=42,
        frames_per_buffer=0,
        start=False,
        stream_callback=capture._on_audio,
    )

    stream.start_stream.assert_called_once_with()


@pytest.mark.anyio
async def test_start_uses_loopback_device_format(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    audio = MagicMock()
    stream = MagicMock()

    device = WasapiLoopbackDevice(
        index=42,
        name="Test Speakers [Loopback]",
        channels=2,
        sample_rate=48_000.0,
    )
    audio.open.return_value = stream

    monkeypatch.setattr(
        "app.audio.capture.pyaudiowpatch.PyAudio",
        lambda: audio,
    )

    fake_device_provider = MagicMock()
    fake_device_provider.get_default.return_value = device

    fake_transport = MagicMock()
    fake_transport.start = AsyncMock()
    fake_transport.stop = AsyncMock()

    capture = PyAudioCapture(
        audio=audio,
        device_provider=fake_device_provider,
        transport=fake_transport,
    )

    try:
        await capture.start()

        assert capture._format is not None
        assert capture._format.sample_rate == 48000
        assert capture._format.channels == 2
        assert capture._format.sample_type == "int16"
    finally:
        await capture.stop()

    fake_transport.start.assert_awaited_once_with()
    fake_transport.stop.assert_awaited_once_with()


def test_audio_callback_creates_and_submits_frame() -> None:
    samples = np.array(
        [
            [100, 200],
            [300, 400],
        ],
        dtype=np.int16,
    )

    fake_audio = MagicMock(spec=pyaudiowpatch.PyAudio)
    fake_device_provider = MagicMock()
    fake_transport = MagicMock()

    capture = PyAudioCapture(
        audio=fake_audio,
        device_provider=fake_device_provider,
        transport=fake_transport,
    )

    capture._format = AudioFormat(
        sample_rate=48_000,
        channels=2,
        sample_type="int16",
    )

    result = capture._on_audio(
        in_data=samples.tobytes(),
        frame_count=2,
        time_info={"input_buffer_adc_time": 123.5},
        status_flags=0,
    )

    assert result == (None, pyaudiowpatch.paContinue)

    fake_transport.submit.assert_called_once()

    frame = fake_transport.submit.call_args.args[0]

    assert isinstance(frame, AudioFrame)
    assert frame.timestamp == 123.5
    assert frame.format.sample_rate == 48_000
    assert frame.format.channels == 2
    np.testing.assert_array_equal(frame.audio, samples)


def test_pyaudio_capture_dependency_boundary() -> None:
    """Test that PyAudioCapture can be instantiated."""
    fake_audio = MagicMock()
    fake_device_provider = MagicMock()
    fake_transport = MagicMock()

    capture = PyAudioCapture(
        audio=fake_audio,
        device_provider=fake_device_provider,
        transport=fake_transport,
    )

    assert capture is not None


@pytest.mark.anyio
async def test_callback_frame_is_received_by_async_consumer() -> None:
    audio = MagicMock()
    device_provider = MagicMock()
    transport = QueuedAudioCapture(max_queue_size=4)

    capture = PyAudioCapture(
        audio=audio,
        device_provider=device_provider,
        transport=transport,
    )

    capture._format = AudioFormat(
        sample_rate=48_000,
        channels=2,
        sample_type="int16",
    )

    received: list[AudioFrame] = []
    received_event = asyncio.Event()

    async def consume() -> None:
        async for frame in capture.frames():
            received.append(frame)
            received_event.set()

    await transport.start()

    consumer = asyncio.create_task(consume())

    try:
        expected = AudioFrame(
            audio=np.array(
                [
                    [100, 200],
                    [300, 400],
                ],
                dtype=np.int16,
            ),
            timestamp=1.0,
            format=AudioFormat(
                sample_rate=48_000,
                channels=2,
                sample_type="int16",
            ),
        )

        result = capture._on_audio(
            in_data=expected.audio.tobytes(),
            frame_count=expected.audio.shape[0],
            time_info={"input_buffer_adc_time": expected.timestamp},
            status_flags=0,
        )

        assert result == (None, pyaudiowpatch.paContinue)

        await asyncio.wait_for(received_event.wait(), timeout=1.0)

        assert len(received) == 1
        assert received[0].timestamp == expected.timestamp
        assert received[0].format == expected.format
        np.testing.assert_array_equal(received[0].audio, expected.audio)

    finally:
        await transport.stop()
        await consumer


@pytest.mark.anyio
async def test_stop_terminates_capture_stream() -> None:
    transport = QueuedAudioCapture(max_queue_size=4)

    audio = MagicMock()
    device_provider = MagicMock()
    device_provider.get_default.side_effect = LookupError

    capture = PyAudioCapture(
        audio=audio,
        device_provider=device_provider,
        transport=transport,
    )

    await capture.start()

    consumer = asyncio.create_task(consume_stream(capture))

    try:
        await capture.stop()

        await asyncio.wait_for(consumer, timeout=1.0)
    finally:
        if not consumer.done():
            consumer.cancel()
            await consumer
