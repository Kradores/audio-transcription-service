from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pyaudiowpatch
import pytest

from app.audio.capture import (
    RECOVERY_INITIAL_DELAY_SECONDS,
    CaptureDeviceProvider,
    CaptureDeviceProviderFactory,
    PyAudioCapture,
    PyAudioFactory,
    QueuedAudioCapture,
    Sleep,
    WasapiAudioFrameFactory,
    WasapiInputDevice,
    WasapiInputDeviceProvider,
    WasapiInputDeviceProviderFactoryImpl,
    WasapiLoopbackDevice,
)
from app.audio.contracts import AudioFormat, AudioFrame
from app.audio.device_monitor import AudioDeviceMonitor
from app.audio.portaudio_refresh import PortAudioRefreshRequester
from app.audio.timeline import AudioTimeline
from app.audio.transport import AudioFrameTransport
from tests.unit.audio.helpers import (
    consume_one,
    consume_stream,
    create_frame,
)


class FakePyAudioFactory:
    def __init__(
        self,
        *instances: pyaudiowpatch.PyAudio,
    ) -> None:
        self._instances = list(instances)
        self.created: list[pyaudiowpatch.PyAudio] = []

    def create(self) -> pyaudiowpatch.PyAudio:
        if not self._instances:
            raise AssertionError("No fake PyAudio instance available")

        audio = self._instances.pop(0)
        self.created.append(audio)

        return audio


class FakeDeviceProviderFactory:
    def __init__(
        self,
        *providers: CaptureDeviceProvider,
    ) -> None:
        self._providers = list(providers)
        self.created_with: list[pyaudiowpatch.PyAudio] = []

    def create(
        self,
        audio: pyaudiowpatch.PyAudio,
    ) -> CaptureDeviceProvider:
        self.created_with.append(audio)

        if not self._providers:
            raise AssertionError("No fake device provider available")

        return self._providers.pop(0)


class FakeAudioDeviceMonitor:
    def __init__(self) -> None:
        self.started = False
        self.stopped = False
        self._handler: Callable[[str | None], None] | None = None

    def set_change_handler(
        self,
        handler: Callable[[str | None], None],
    ) -> None:
        self._handler = handler

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True

    def signal_change(
        self,
        endpoint_id: str = "endpoint-123",
    ) -> None:
        if self._handler is None:
            raise AssertionError("change handler was not registered")

        self._handler(endpoint_id)


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


class FakePortAudioRefreshRequester:
    def __init__(self) -> None:
        self.signals = 0
        self.requests = 0

    def signal_refresh_requested(self) -> None:
        self.signals += 1

    async def request_refresh(self) -> None:
        self.requests += 1


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


class FakeAudioTimeline:
    def __init__(self, now: float) -> None:
        self.current = now

    def now(self) -> float:
        return self.current


class ControlledSleep:
    def __init__(self) -> None:
        self.calls: list[float] = []
        self._waiters: asyncio.Queue[asyncio.Future[None]] = asyncio.Queue()

    async def __call__(self, delay: float) -> None:
        self.calls.append(delay)

        future = asyncio.get_running_loop().create_future()
        await self._waiters.put(future)

        await future

    async def release_next(self) -> None:
        future = await self._waiters.get()

        if not future.done():
            future.set_result(None)

        await asyncio.sleep(0)


async def _wait_until(
    condition: Callable[[], bool],
) -> None:
    for _ in range(100):
        if condition():
            return

        await asyncio.sleep(0)

    raise AssertionError("condition was not reached")


async def _yielding_sleep(delay: float) -> None:
    await asyncio.sleep(0)


def _create_capture(
    *,
    audio_factory: PyAudioFactory | None = None,
    device_provider_factory: CaptureDeviceProviderFactory | None = None,
    device_monitor: AudioDeviceMonitor | None = None,
    transport: QueuedAudioCapture | None = None,
    timeline: AudioTimeline | None = None,
    portaudio_refresh: PortAudioRefreshRequester | None = None,
    sleep: Sleep = asyncio.sleep,
) -> PyAudioCapture:
    if audio_factory is None:
        audio_factory = MagicMock()

    if device_provider_factory is None:
        device_provider_factory = MagicMock()

    if device_monitor is None:
        device_monitor = MagicMock()

    if transport is None:
        transport = MagicMock()

    if timeline is None:
        timeline = MagicMock()

    if portaudio_refresh is None:
        portaudio_refresh = FakePortAudioRefreshRequester()

    return PyAudioCapture(
        audio_factory=audio_factory,
        device_provider_factory=device_provider_factory,
        device_monitor=device_monitor,
        transport=transport,
        timeline=timeline,
        portaudio_refresh=portaudio_refresh,
        sleep=sleep,
    )


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

    audio.open.return_value = stream

    monitor = FakeAudioDeviceMonitor()

    capture = _create_capture(
        audio_factory=FakePyAudioFactory(audio),
        device_provider_factory=FakeDeviceProviderFactory(device_provider),
        device_monitor=monitor,
        transport=QueuedAudioCapture(max_queue_size=4),
        sleep=_yielding_sleep,
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
    device_provider = MagicMock()
    device_provider.get_default.side_effect = LookupError

    monitor = FakeAudioDeviceMonitor()

    capture = _create_capture(
        device_provider_factory=FakeDeviceProviderFactory(device_provider),
        device_monitor=monitor,
        transport=QueuedAudioCapture(max_queue_size=4),
        sleep=_yielding_sleep,
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

    capture = _create_capture(
        audio_factory=FakePyAudioFactory(audio),
        device_provider_factory=FakeDeviceProviderFactory(fake_device_provider),
        transport=fake_transport,
        sleep=_yielding_sleep,
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

    capture = _create_capture(
        audio_factory=FakePyAudioFactory(audio),
        device_provider_factory=FakeDeviceProviderFactory(fake_device_provider),
        transport=fake_transport,
        sleep=_yielding_sleep,
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


def test_pyaudio_capture_dependency_boundary() -> None:
    """Test that PyAudioCapture can be instantiated."""
    capture = _create_capture()

    assert capture is not None


@pytest.mark.anyio
async def test_callback_frame_is_received_by_async_consumer() -> None:
    transport = QueuedAudioCapture(max_queue_size=4)
    fake_timeline = FakeAudioTimeline(0.0)

    capture = _create_capture(
        transport=transport,
        timeline=fake_timeline,
        sleep=_yielding_sleep,
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
            time_info={
                "input_buffer_adc_time": expected.timestamp,
                "current_time": expected.timestamp,
            },
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

    device_provider = MagicMock()
    device_provider.get_default.side_effect = LookupError

    capture = _create_capture(
        device_provider_factory=FakeDeviceProviderFactory(device_provider),
        transport=transport,
        sleep=_yielding_sleep,
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

    capture = _create_capture(
        audio_factory=FakePyAudioFactory(MagicMock()),
        device_provider_factory=FakeDeviceProviderFactory(device_provider),
        transport=transport,
        sleep=_yielding_sleep,
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

    capture = _create_capture(
        transport=QueuedAudioCapture(max_queue_size=4),
        sleep=_yielding_sleep,
    )

    capture.set_discontinuity_handler(handler)

    assert capture._discontinuity_handler is handler


@pytest.mark.anyio
async def test_inactive_running_stream_invokes_discontinuity_handler() -> None:
    transport = QueuedAudioCapture(max_queue_size=4)

    device = WasapiLoopbackDevice(
        index=42,
        name="Test Speakers [Loopback]",
        channels=2,
        sample_rate=48_000,
    )

    first_stream = FakeStream(active=False)
    recovered_stream = FakeStream(active=True)

    first_audio = MagicMock()
    second_audio = MagicMock()

    first_audio.open.return_value = first_stream
    second_audio.open.return_value = recovered_stream

    first_provider = MagicMock()
    first_provider.get_default.return_value = device

    second_provider = MagicMock()
    second_provider.get_default.return_value = device

    discontinuity_event = asyncio.Event()
    discontinuities: list[int] = []

    def on_discontinuity() -> None:
        discontinuities.append(1)
        discontinuity_event.set()

    capture = _create_capture(
        audio_factory=FakePyAudioFactory(
            first_audio,
            second_audio,
        ),
        device_provider_factory=FakeDeviceProviderFactory(
            first_provider,
            second_provider,
        ),
        device_monitor=FakeAudioDeviceMonitor(),
        transport=transport,
        sleep=_yielding_sleep,
    )

    capture.set_discontinuity_handler(on_discontinuity)

    await capture.start()

    try:
        await asyncio.wait_for(
            discontinuity_event.wait(),
            timeout=1.0,
        )

        for _ in range(20):
            if capture._stream is recovered_stream:
                break

            await asyncio.sleep(0)

        assert discontinuities == [1]

        assert first_stream.stop_called
        assert first_stream.close_called
        first_audio.terminate.assert_called_once_with()

        assert recovered_stream.start_called
        assert capture._stream is recovered_stream

    finally:
        await capture.stop()


@pytest.mark.anyio
async def test_close_stream_clears_stream_reference() -> None:
    # Arrange
    stream = FakeStream(active=False)

    capture = _create_capture(
        transport=QueuedAudioCapture(max_queue_size=4),
        sleep=_yielding_sleep,
    )
    capture._stream = stream

    # Act
    capture._close_stream()

    # Assert
    assert capture._stream is None
    assert stream.stop_called
    assert stream.close_called


def test_conversation_timeline_survives_stream_recovery() -> None:
    fake_transport = MagicMock()
    submit = MagicMock()
    fake_transport.submit = submit
    fake_timeline = FakeAudioTimeline(10.0)

    monitor = FakeAudioDeviceMonitor()

    capture = _create_capture(
        audio_factory=FakePyAudioFactory(MagicMock()),
        device_provider_factory=FakeDeviceProviderFactory(MagicMock()),
        device_monitor=monitor,
        transport=fake_transport,
        timeline=fake_timeline,
        sleep=_yielding_sleep,
    )

    capture._format = AudioFormat(
        sample_rate=48_000,
        channels=2,
        sample_type="int16",
    )

    samples = np.zeros((480, 2), dtype=np.int16)

    capture._on_audio(
        in_data=samples.tobytes(),
        frame_count=480,
        time_info={},
        status_flags=0,
    )

    first_frame = submit.call_args_list[0].args[0]

    assert first_frame.timestamp == pytest.approx(9.99)

    # Simulate a fresh native stream after recovery.
    capture._next_frame_timestamp = None
    fake_timeline.current = 20.0

    capture._on_audio(
        in_data=samples.tobytes(),
        frame_count=480,
        time_info={},
        status_flags=0,
    )

    recovered_frame = submit.call_args_list[1].args[0]

    assert recovered_frame.timestamp == pytest.approx(19.99)


@pytest.mark.anyio
async def test_start_starts_audio_device_monitor() -> None:
    audio = MagicMock()

    device = WasapiLoopbackDevice(
        index=42,
        name="Speakers [Loopback]",
        channels=2,
        sample_rate=48_000,
    )

    device_provider = MagicMock()
    device_provider.get_default.return_value = device

    stream = FakeStream(active=True)
    audio.open.return_value = stream

    monitor = FakeAudioDeviceMonitor()

    capture = _create_capture(
        audio_factory=FakePyAudioFactory(audio),
        device_provider_factory=FakeDeviceProviderFactory(device_provider),
        device_monitor=monitor,
        transport=QueuedAudioCapture(max_queue_size=4),
        sleep=_yielding_sleep,
    )

    try:
        await capture.start()

        assert monitor.started
    finally:
        await capture.stop()


@pytest.mark.anyio
async def test_stop_stops_audio_device_monitor() -> None:
    provider = MagicMock()
    provider.get_default.side_effect = LookupError

    monitor = FakeAudioDeviceMonitor()

    capture = _create_capture(
        device_provider_factory=FakeDeviceProviderFactory(provider),
        device_monitor=monitor,
        transport=QueuedAudioCapture(max_queue_size=4),
        sleep=_yielding_sleep,
    )

    await capture.start()
    await capture.stop()

    assert monitor.stopped


def test_wasapi_input_device_provider_returns_default_wasapi_input() -> None:
    # Arrange
    audio = MagicMock()

    audio.get_default_wasapi_device.return_value = {
        "index": 14,
        "name": "Microphone Array (Realtek(R) Audio)",
        "maxInputChannels": 1,
        "defaultSampleRate": 16_000.0,
    }

    provider = WasapiInputDeviceProvider(audio)

    # Act
    device = provider.get_default()

    # Assert
    assert device == WasapiInputDevice(
        index=14,
        name="Microphone Array (Realtek(R) Audio)",
        channels=1,
        sample_rate=16_000.0,
    )

    audio.get_default_wasapi_device.assert_called_once_with(
        d_in=True,
    )


def test_wasapi_input_device_provider_factory_binds_audio_instance() -> None:
    # Arrange
    audio = MagicMock()
    factory = WasapiInputDeviceProviderFactoryImpl()

    # Act
    provider = factory.create(audio)

    # Assert
    assert isinstance(provider, WasapiInputDeviceProvider)


def test_wasapi_input_device_provider_rejects_device_without_input_channels() -> None:
    # Arrange
    audio = MagicMock()

    audio.get_default_wasapi_device.return_value = {
        "index": 15,
        "name": "Invalid input",
        "maxInputChannels": 0,
        "defaultSampleRate": 48_000.0,
    }

    provider = WasapiInputDeviceProvider(audio)

    # Act / Assert
    with pytest.raises(
        LookupError,
        match="default input device has no input channels",
    ):
        provider.get_default()

    audio.get_default_wasapi_device.assert_called_once_with(
        d_in=True,
    )


def test_wasapi_input_device_provider_does_not_use_global_default_input() -> None:
    # Arrange
    audio = MagicMock()

    audio.get_default_wasapi_device.return_value = {
        "index": 14,
        "name": "WASAPI microphone",
        "maxInputChannels": 1,
        "defaultSampleRate": 16_000.0,
    }

    provider = WasapiInputDeviceProvider(audio)

    # Act
    provider.get_default()

    # Assert
    audio.get_default_wasapi_device.assert_called_once_with(
        d_in=True,
    )
    audio.get_default_input_device_info.assert_not_called()


@pytest.mark.anyio
async def test_start_opens_default_microphone_input_stream() -> None:
    # Arrange
    audio = MagicMock()
    stream = MagicMock()
    audio.open.return_value = stream

    device = WasapiInputDevice(
        index=15,
        name="Microphone Array (Realtek(R) Audio)",
        channels=2,
        sample_rate=48_000.0,
    )

    device_provider = MagicMock(spec=WasapiInputDeviceProvider)
    device_provider.get_default.return_value = device

    monitor = FakeAudioDeviceMonitor()

    capture = _create_capture(
        audio_factory=FakePyAudioFactory(audio),
        device_provider_factory=FakeDeviceProviderFactory(
            device_provider,
        ),
        device_monitor=monitor,
        transport=QueuedAudioCapture(max_queue_size=4),
        sleep=_yielding_sleep,
    )

    try:
        await capture.start()

        device_provider.get_default.assert_called_once_with()

        audio.open.assert_called_once_with(
            rate=48_000,
            channels=2,
            format=pyaudiowpatch.paInt16,
            input=True,
            input_device_index=15,
            frames_per_buffer=0,
            start=False,
            stream_callback=capture._on_audio,
        )

        stream.start_stream.assert_called_once_with()

    finally:
        await capture.stop()


def test_two_captures_share_conversation_timeline() -> None:
    timeline = FakeAudioTimeline(2.0)

    system_transport = MagicMock()
    microphone_transport = MagicMock()

    system_capture = _create_capture(
        audio_factory=FakePyAudioFactory(MagicMock()),
        device_provider_factory=FakeDeviceProviderFactory(MagicMock()),
        device_monitor=FakeAudioDeviceMonitor(),
        transport=system_transport,
        timeline=timeline,
        sleep=_yielding_sleep,
    )

    microphone_capture = _create_capture(
        audio_factory=FakePyAudioFactory(MagicMock()),
        device_provider_factory=FakeDeviceProviderFactory(MagicMock()),
        device_monitor=FakeAudioDeviceMonitor(),
        transport=microphone_transport,
        timeline=timeline,
        sleep=_yielding_sleep,
    )

    system_capture._format = AudioFormat(
        sample_rate=48_000,
        channels=2,
        sample_type="int16",
    )

    microphone_capture._format = AudioFormat(
        sample_rate=48_000,
        channels=1,
        sample_type="int16",
    )

    system_audio = np.zeros((480, 2), dtype=np.int16)
    microphone_audio = np.zeros((480, 1), dtype=np.int16)

    system_capture._on_audio(
        in_data=system_audio.tobytes(),
        frame_count=480,
        time_info={},
        status_flags=0,
    )

    timeline.current = 5.0

    microphone_capture._on_audio(
        in_data=microphone_audio.tobytes(),
        frame_count=480,
        time_info={},
        status_flags=0,
    )

    system_frame = system_transport.submit.call_args.args[0]
    microphone_frame = microphone_transport.submit.call_args.args[0]

    assert system_frame.timestamp == pytest.approx(1.99)
    assert microphone_frame.timestamp == pytest.approx(4.99)


def test_audio_callback_advances_timestamp_by_frame_duration() -> None:
    fake_transport = MagicMock()
    fake_timeline = FakeAudioTimeline(5.0)

    capture = _create_capture(
        audio_factory=FakePyAudioFactory(MagicMock()),
        device_provider_factory=FakeDeviceProviderFactory(MagicMock()),
        device_monitor=FakeAudioDeviceMonitor(),
        transport=fake_transport,
        timeline=fake_timeline,
        sleep=_yielding_sleep,
    )

    capture._format = AudioFormat(
        sample_rate=48_000,
        channels=2,
        sample_type="int16",
    )

    samples = np.zeros((480, 2), dtype=np.int16)

    capture._on_audio(
        in_data=samples.tobytes(),
        frame_count=480,
        time_info={},
        status_flags=0,
    )

    capture._on_audio(
        in_data=samples.tobytes(),
        frame_count=480,
        time_info={},
        status_flags=0,
    )

    first_frame = fake_transport.submit.call_args_list[0].args[0]
    second_frame = fake_transport.submit.call_args_list[1].args[0]

    assert first_frame.timestamp == pytest.approx(4.99)
    assert second_frame.timestamp == pytest.approx(5.00)


def test_active_stream_timestamp_progression_ignores_callback_timing_jitter() -> None:
    fake_transport = MagicMock()
    fake_timeline = FakeAudioTimeline(5.0)

    capture = _create_capture(
        audio_factory=FakePyAudioFactory(MagicMock()),
        device_provider_factory=FakeDeviceProviderFactory(MagicMock()),
        device_monitor=FakeAudioDeviceMonitor(),
        transport=fake_transport,
        timeline=fake_timeline,
        sleep=_yielding_sleep,
    )

    capture._format = AudioFormat(
        sample_rate=48_000,
        channels=2,
        sample_type="int16",
    )

    samples = np.zeros((480, 2), dtype=np.int16)

    capture._on_audio(
        in_data=samples.tobytes(),
        frame_count=480,
        time_info={},
        status_flags=0,
    )

    # Simulate delayed callback scheduling.
    fake_timeline.current = 5.037

    capture._on_audio(
        in_data=samples.tobytes(),
        frame_count=480,
        time_info={},
        status_flags=0,
    )

    first_frame = fake_transport.submit.call_args_list[0].args[0]
    second_frame = fake_transport.submit.call_args_list[1].args[0]

    assert first_frame.timestamp == pytest.approx(4.99)
    assert second_frame.timestamp == pytest.approx(5.00)


def test_timestamp_progression_uses_actual_frame_count() -> None:
    fake_transport = MagicMock()
    fake_timeline = FakeAudioTimeline(10.0)

    capture = _create_capture(
        audio_factory=FakePyAudioFactory(MagicMock()),
        device_provider_factory=FakeDeviceProviderFactory(MagicMock()),
        device_monitor=FakeAudioDeviceMonitor(),
        transport=fake_transport,
        timeline=fake_timeline,
        sleep=_yielding_sleep,
    )

    capture._format = AudioFormat(
        sample_rate=44_100,
        channels=2,
        sample_type="int16",
    )

    samples = np.zeros((576, 2), dtype=np.int16)

    capture._on_audio(
        in_data=samples.tobytes(),
        frame_count=576,
        time_info={},
        status_flags=0,
    )

    capture._on_audio(
        in_data=samples.tobytes(),
        frame_count=576,
        time_info={},
        status_flags=0,
    )

    first_frame = fake_transport.submit.call_args_list[0].args[0]
    second_frame = fake_transport.submit.call_args_list[1].args[0]

    duration = 576 / 44_100

    assert first_frame.timestamp == pytest.approx(10.0 - duration)
    assert second_frame.timestamp == pytest.approx(10.0)


def test_first_frame_timestamp_is_clamped_to_zero() -> None:
    fake_transport = MagicMock()
    fake_timeline = FakeAudioTimeline(0.0)

    capture = _create_capture(
        audio_factory=FakePyAudioFactory(MagicMock()),
        device_provider_factory=FakeDeviceProviderFactory(MagicMock()),
        device_monitor=FakeAudioDeviceMonitor(),
        transport=fake_transport,
        timeline=fake_timeline,
        sleep=_yielding_sleep,
    )

    capture._format = AudioFormat(
        sample_rate=48_000,
        channels=2,
        sample_type="int16",
    )

    samples = np.zeros((480, 2), dtype=np.int16)

    capture._on_audio(
        in_data=samples.tobytes(),
        frame_count=480,
        time_info={},
        status_flags=0,
    )

    frame = fake_transport.submit.call_args.args[0]

    assert frame.timestamp == 0.0


@pytest.mark.anyio
async def test_recovery_retries_when_open_raises_oserror() -> None:
    sleep = ControlledSleep()

    capture = _create_capture(
        sleep=sleep,
    )

    capture._started = True
    capture._recovery_active = True

    successful_stream = MagicMock()
    successful_stream.is_active.return_value = True

    attempts = 0

    async def open_fresh_stream() -> None:
        nonlocal attempts

        attempts += 1

        if attempts == 1:
            raise OSError(-9992, "Insufficient memory")

        capture._stream = successful_stream

    with (
        patch.object(
            capture,
            "_open_fresh_stream",
            new_callable=AsyncMock,
        ) as open_fresh_stream_mock,
        patch.object(
            capture,
            "_dispose_audio_session",
        ) as dispose_audio_session,
    ):
        open_fresh_stream_mock.side_effect = open_fresh_stream

        lifecycle = asyncio.create_task(
            capture._run(),
        )

        await _wait_until(
            lambda: attempts == 1,
        )

        assert not lifecycle.done()

        await _wait_until(
            lambda: len(sleep.calls) >= 1,
        )

        await sleep.release_next()

        await _wait_until(
            lambda: attempts == 2,
        )

        assert not lifecycle.done()
        assert capture._recovery_active is False

        capture._started = False
        lifecycle.cancel()

        with pytest.raises(asyncio.CancelledError):
            await lifecycle

        assert dispose_audio_session.call_count >= 1


@pytest.mark.anyio
async def test_recovery_retries_when_default_device_is_unavailable() -> None:
    sleep = ControlledSleep()

    capture = _create_capture(
        sleep=sleep,
    )

    capture._started = True
    capture._recovery_active = True

    successful_stream = MagicMock()
    successful_stream.is_active.return_value = True

    attempts = 0

    async def open_fresh_stream() -> None:
        nonlocal attempts

        attempts += 1

        if attempts == 1:
            raise LookupError("no default device")

        capture._stream = successful_stream

    with (
        patch.object(
            capture,
            "_open_fresh_stream",
            new_callable=AsyncMock,
        ) as open_fresh_stream_mock,
        patch.object(
            capture,
            "_dispose_audio_session",
        ) as dispose_audio_session,
    ):
        open_fresh_stream_mock.side_effect = open_fresh_stream

        lifecycle = asyncio.create_task(
            capture._run(),
        )

        await _wait_until(
            lambda: attempts == 1,
        )

        assert not lifecycle.done()

        await _wait_until(
            lambda: len(sleep.calls) >= 1,
        )

        await sleep.release_next()

        await _wait_until(
            lambda: attempts == 2,
        )

        assert not lifecycle.done()
        assert capture._recovery_active is False

        capture._started = False
        lifecycle.cancel()

        with pytest.raises(asyncio.CancelledError):
            await lifecycle

        assert dispose_audio_session.call_count >= 1


def test_begin_recovery_signals_discontinuity_only_once() -> None:
    capture = _create_capture()

    handler = MagicMock()
    capture.set_discontinuity_handler(handler)

    capture._begin_recovery(
        reason="default_device_changed",
    )
    capture._begin_recovery(
        reason="default_device_changed",
    )
    capture._begin_recovery(
        reason="stream_inactive",
    )

    handler.assert_called_once_with()


def test_prepare_for_portaudio_refresh_disposes_native_session() -> None:
    capture = _create_capture()
    capture._started = True

    discontinuity_handler = MagicMock()
    capture._discontinuity_handler = discontinuity_handler

    with patch.object(
        capture,
        "_dispose_audio_session",
    ) as dispose_audio_session:
        capture.prepare_for_portaudio_refresh()

    dispose_audio_session.assert_called_once_with()
    discontinuity_handler.assert_called_once_with()


def test_prepare_for_portaudio_refresh_does_nothing_when_not_started() -> None:
    capture = _create_capture()

    with patch.object(
        capture,
        "_dispose_audio_session",
    ) as dispose_audio_session:
        capture.prepare_for_portaudio_refresh()

    dispose_audio_session.assert_not_called()


@pytest.mark.anyio
async def test_restore_after_portaudio_refresh_opens_fresh_stream() -> None:
    capture = _create_capture()
    capture._started = True
    capture._recovery_active = True

    with patch.object(
        capture,
        "_open_fresh_stream",
        new_callable=AsyncMock,
    ) as open_fresh_stream:
        await capture.restore_after_portaudio_refresh()

    open_fresh_stream.assert_awaited_once_with()
    assert capture._recovery_active is False


@pytest.mark.anyio
async def test_restore_after_portaudio_refresh_does_nothing_when_not_started() -> None:
    capture = _create_capture()

    with patch.object(
        capture,
        "_open_fresh_stream",
        new_callable=AsyncMock,
    ) as open_fresh_stream:
        await capture.restore_after_portaudio_refresh()

    open_fresh_stream.assert_not_awaited()


@pytest.mark.anyio
async def test_restore_after_portaudio_refresh_propagates_device_unavailable() -> None:
    capture = _create_capture()
    capture._started = True

    with (
        patch.object(
            capture,
            "_open_fresh_stream",
            new_callable=AsyncMock,
            side_effect=LookupError("device unavailable"),
        ),
        pytest.raises(
            LookupError,
            match="device unavailable",
        ),
    ):
        await capture.restore_after_portaudio_refresh()


@pytest.mark.anyio
async def test_default_device_change_requests_process_wide_refresh() -> None:
    requester = FakePortAudioRefreshRequester()

    device = WasapiLoopbackDevice(
        index=42,
        name="Test Speakers [Loopback]",
        channels=2,
        sample_rate=48_000,
    )

    device_provider = MagicMock()
    device_provider.get_default.return_value = device

    capture = _create_capture(
        device_provider_factory=FakeDeviceProviderFactory(device_provider),
        portaudio_refresh=requester,
    )

    capture._started = True

    capture._signal_default_device_changed()

    lifecycle = asyncio.create_task(
        capture._run(),
    )

    await _wait_until(
        lambda: requester.requests == 1,
    )

    capture._started = False
    lifecycle.cancel()

    with pytest.raises(asyncio.CancelledError):
        await lifecycle

    assert requester.requests == 1


@pytest.mark.anyio
async def test_inactive_stream_uses_source_local_recovery() -> None:
    requester = FakePortAudioRefreshRequester()

    capture = _create_capture(
        portaudio_refresh=requester,
        sleep=_yielding_sleep,
    )

    capture._started = True

    stream = MagicMock()
    stream.is_active.return_value = False
    capture._stream = stream

    with (
        patch.object(
            capture,
            "_open_fresh_stream",
            new_callable=AsyncMock,
            side_effect=asyncio.CancelledError,
        ) as open_fresh_stream,
        pytest.raises(asyncio.CancelledError),
    ):
        await capture._run()

    open_fresh_stream.assert_awaited_once_with()

    assert requester.requests == 0
    assert capture._recovery_active is True
    assert capture._stream is None

    stream.stop_stream.assert_called_once_with()
    stream.close.assert_called_once_with()


@pytest.mark.anyio
async def test_start_enters_recovery_when_initial_device_discovery_raises_oserror() -> None:
    # Arrange
    first_audio = MagicMock()
    second_audio = MagicMock()

    first_provider = MagicMock()
    first_provider.get_default.side_effect = OSError(
        -9996,
        "Invalid device info",
    )

    recovered_device = WasapiInputDevice(
        index=14,
        name="Headset",
        channels=1,
        sample_rate=16_000.0,
    )

    second_provider = MagicMock()
    second_provider.get_default.return_value = recovered_device

    recovered_stream = FakeStream(active=True)
    second_audio.open.return_value = recovered_stream

    capture = _create_capture(
        audio_factory=FakePyAudioFactory(
            first_audio,
            second_audio,
        ),
        device_provider_factory=FakeDeviceProviderFactory(
            first_provider,
            second_provider,
        ),
        device_monitor=FakeAudioDeviceMonitor(),
        transport=QueuedAudioCapture(max_queue_size=4),
        sleep=_yielding_sleep,
    )

    # Act
    await capture.start()

    try:
        for _ in range(20):
            if capture._stream is recovered_stream:
                break

            await asyncio.sleep(0)

        # Assert
        assert capture._stream is recovered_stream

        first_audio.terminate.assert_called_once_with()
        second_provider.get_default.assert_called_once_with()
        assert recovered_stream.is_active()

    finally:
        await capture.stop()


@pytest.mark.anyio
async def test_recovery_retry_wait_is_interrupted_by_default_device_change() -> None:
    # Arrange
    sleep = ControlledSleep()

    capture = _create_capture(
        sleep=sleep,
    )

    capture._started = True

    wait_task = asyncio.create_task(
        capture._wait_for_recovery_retry(5.0),
    )

    await _wait_until(
        lambda: sleep.calls == [5.0],
    )

    # Act
    capture._signal_default_device_changed()

    interrupted = await wait_task

    # Assert
    assert interrupted is True
    assert capture._device_change_event.is_set()


@pytest.mark.anyio
async def test_recovery_retry_wait_completes_after_delay_without_device_change() -> None:
    # Arrange
    sleep = ControlledSleep()

    capture = _create_capture(
        sleep=sleep,
    )

    capture._started = True

    wait_task = asyncio.create_task(
        capture._wait_for_recovery_retry(5.0),
    )

    await _wait_until(
        lambda: sleep.calls == [5.0],
    )

    # Act
    await sleep.release_next()

    interrupted = await wait_task

    # Assert
    assert interrupted is False
    assert not capture._device_change_event.is_set()


@pytest.mark.anyio
async def test_default_device_change_interrupts_device_unavailable_backoff() -> None:
    # Arrange
    sleep = ControlledSleep()
    requester = FakePortAudioRefreshRequester()

    capture = _create_capture(
        portaudio_refresh=requester,
        sleep=sleep,
    )

    capture._started = True
    capture._recovery_active = True
    capture._stream = None

    with patch.object(
        capture,
        "_open_fresh_stream",
        new_callable=AsyncMock,
        side_effect=OSError(
            -9996,
            "Invalid device info",
        ),
    ):
        lifecycle = asyncio.create_task(
            capture._run(),
        )

        await _wait_until(
            lambda: sleep.calls == [RECOVERY_INITIAL_DELAY_SECONDS],
        )

        # Act
        capture._signal_default_device_changed()

        await _wait_until(
            lambda: requester.requests == 1,
        )

        # Assert
        assert requester.requests == 1

        capture._started = False
        lifecycle.cancel()

        with pytest.raises(asyncio.CancelledError):
            await lifecycle


@pytest.mark.anyio
async def test_source_local_recovery_does_not_open_stream_during_portaudio_refresh() -> None:
    capture = _create_capture(
        sleep=AsyncMock(
            side_effect=asyncio.CancelledError,
        ),
    )

    capture._started = True
    capture._stream = None
    capture._portaudio_refresh_active = True

    with patch.object(
        capture,
        "_open_fresh_stream",
        new_callable=AsyncMock,
    ) as open_fresh_stream, pytest.raises(asyncio.CancelledError):
        await capture._run()

    open_fresh_stream.assert_not_awaited()


def test_prepare_for_portaudio_refresh_blocks_source_local_recovery() -> None:
    capture = _create_capture()
    capture._started = True

    capture.prepare_for_portaudio_refresh()

    assert capture._portaudio_refresh_active is True


@pytest.mark.anyio
async def test_failed_coordinated_restore_reenables_source_local_recovery() -> None:
    capture = _create_capture()
    capture._started = True
    capture._portaudio_refresh_active = True

    with patch.object(
        capture,
        "_open_fresh_stream",
        new_callable=AsyncMock,
        side_effect=OSError(-9996, "Invalid device info"),
    ), pytest.raises(OSError):
        await capture.restore_after_portaudio_refresh()

    assert capture._portaudio_refresh_active is False
