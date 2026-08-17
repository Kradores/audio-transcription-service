from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
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

    def set_discontinuity_handler(
        self,
        handler: Callable[[], None],
    ) -> None:
        self._discontinuity_handler = handler

    def signal_discontinuity(self) -> None:
        if self._discontinuity_handler is None:
            raise AssertionError("discontinuity handler was not registered")

        self._discontinuity_handler()


class FakeStream(pyaudiowpatch.Stream):
    def __init__(self, active: bool) -> None:
        self.active = active
        self.stop_called = False
        self.close_called = False
        self.start_called = False

    def is_active(self) -> bool:
        return self.active

    def start_stream(self) -> None:
        self.start_called = True

    def stop_stream(self) -> None:
        self.stop_called = True

    def close(self) -> None:
        self.close_called = True


class TransitioningFakeStream(FakeStream):
    def __init__(self) -> None:
        super().__init__(active=True)
        self._is_active_calls = 0

    def is_active(self) -> bool:
        self._is_active_calls += 1

        if self._is_active_calls == 1:
            return True

        self.active = False
        return False


class BlockingSleep:
    def __init__(self) -> None:
        self.called = asyncio.Event()
        self.release = asyncio.Event()

    async def __call__(self, delay: float) -> None:
        self.called.set()
        await self.release.wait()


recorded_delays: list[float] = []


async def immediate_sleep(delay: float) -> None:
    recorded_delays.append(delay)


async def yielding_sleep(delay: float) -> None:
    await asyncio.sleep(0)


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


def test_audio_callback_creates_frame_with_capture_relative_timestamp() -> None:
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

    capture._on_audio(
        in_data=samples.tobytes(),
        frame_count=2,
        time_info={"input_buffer_adc_time": 123.5},
        status_flags=0,
    )

    capture._on_audio(
        in_data=samples.tobytes(),
        frame_count=2,
        time_info={"input_buffer_adc_time": 123.52},
        status_flags=0,
    )

    first_frame = fake_transport.submit.call_args_list[0].args[0]
    second_frame = fake_transport.submit.call_args_list[1].args[0]

    assert first_frame.timestamp == 0.0
    assert second_frame.timestamp ==  pytest.approx(0.02)

    assert first_frame.format.sample_rate == 48_000
    assert first_frame.format.channels == 2
    np.testing.assert_array_equal(first_frame.audio, samples)


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
            timestamp=0,
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


@pytest.mark.anyio
async def test_set_discontinuity_handler_after_start_raises() -> None:
    # Arrange
    transport = QueuedAudioCapture(max_queue_size=4)
    device = WasapiLoopbackDevice(
        index=42,
        name="Test Speakers [Loopback]",
        channels=2,
        sample_rate=48_000,
    )

    device_provider = MagicMock()
    device_provider.get_default.return_value = device

    capture = PyAudioCapture(
        audio=MagicMock(),
        device_provider=device_provider,
        transport=transport,
    )

    await capture.start()

    # Act / Assert
    with pytest.raises(
        RuntimeError,
        match="cannot be changed after capture has started",
    ):
        capture.set_discontinuity_handler(lambda: None)

    await capture.stop()


def test_set_discontinuity_handler_before_start() -> None:
    def handler() -> None: ...

    capture = PyAudioCapture(
        audio=MagicMock(),
        device_provider=MagicMock(),
        transport=MagicMock(),
    )

    capture.set_discontinuity_handler(handler)

    assert capture._discontinuity_handler is handler


@pytest.mark.anyio
async def test_inactive_running_stream_invokes_discontinuity_handler() -> None:
    # Arrange
    transport = QueuedAudioCapture(max_queue_size=4)

    device = WasapiLoopbackDevice(
        index=42,
        name="Test Speakers [Loopback]",
        channels=2,
        sample_rate=48_000,
    )

    first_stream = FakeStream(active=False)
    recovered_stream = FakeStream(active=True)

    audio = MagicMock()
    audio.open.side_effect = [
        first_stream,
        recovered_stream,
    ]

    device_provider = MagicMock()
    device_provider.get_default.return_value = device

    discontinuity_event = asyncio.Event()
    discontinuities: list[int] = []

    def on_discontinuity() -> None:
        discontinuities.append(1)
        discontinuity_event.set()

    capture = PyAudioCapture(
        audio=audio,
        device_provider=device_provider,
        transport=transport,
        sleep=yielding_sleep,
    )

    capture.set_discontinuity_handler(on_discontinuity)

    # Act
    await capture.start()

    try:
        await asyncio.wait_for(
            discontinuity_event.wait(),
            timeout=1.0,
        )

        # Assert
        assert discontinuities == [1]
        assert first_stream.stop_called
        assert first_stream.close_called
        assert recovered_stream.start_called
        assert audio.open.call_count == 2
        assert capture._stream is recovered_stream
    finally:
        await capture.stop()


@pytest.mark.anyio
async def test_initial_lookup_error_does_not_invoke_discontinuity_handler() -> None:
    # Arrange
    transport = QueuedAudioCapture(max_queue_size=4)

    audio = MagicMock()
    device_provider = MagicMock()
    device_provider.get_default.side_effect = LookupError

    sleep = AsyncMock()

    discontinuities: list[int] = []

    capture = PyAudioCapture(
        audio=audio,
        device_provider=device_provider,
        transport=transport,
        sleep=sleep,
    )

    capture.set_discontinuity_handler(
        lambda: discontinuities.append(1),
    )

    # Act
    await capture.start()

    await asyncio.sleep(0)

    # Assert
    assert discontinuities == []

    await capture.stop()


@pytest.mark.anyio
async def test_close_stream_clears_stream_reference() -> None:
    # Arrange
    stream = FakeStream(active=False)

    capture = PyAudioCapture(
        audio=MagicMock(),
        device_provider=MagicMock(),
        transport=MagicMock(),
    )
    capture._stream = stream

    # Act
    capture._close_stream()

    # Assert
    assert capture._stream is None
    assert stream.stop_called
    assert stream.close_called


def test_capture_timestamp_origin_survives_stream_recovery() -> None:
    fake_transport = MagicMock()
    submit = MagicMock()
    fake_transport.submit = submit

    capture = PyAudioCapture(
        audio=MagicMock(spec=pyaudiowpatch.PyAudio),
        device_provider=MagicMock(),
        transport=fake_transport,
    )

    capture._format = AudioFormat(
        sample_rate=48_000,
        channels=2,
        sample_type="int16",
    )

    samples = np.zeros((2, 2), dtype=np.int16)

    capture._on_audio(
        in_data=samples.tobytes(),
        frame_count=2,
        time_info={"input_buffer_adc_time": 100.0},
        status_flags=0,
    )

    capture._on_audio(
        in_data=samples.tobytes(),
        frame_count=2,
        time_info={"input_buffer_adc_time": 100.02},
        status_flags=0,
    )

    first_frame = submit.call_args_list[0].args[0]
    second_frame = submit.call_args_list[1].args[0]

    assert first_frame.timestamp == 0.0
    assert second_frame.timestamp == pytest.approx(0.02)

    # Simulate a recovered stream whose backend clock has advanced.
    capture._on_audio(
        in_data=samples.tobytes(),
        frame_count=2,
        time_info={"input_buffer_adc_time": 101.0},
        status_flags=0,
    )

    recovered_frame = submit.call_args_list[2].args[0]

    assert recovered_frame.timestamp == 1.0
