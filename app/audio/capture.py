from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from queue import Full, Queue
from threading import Lock
from typing import Protocol

import numpy as np
import pyaudiowpatch

from app.audio.contracts import AudioFormat, AudioFrame
from app.audio.device_monitor import AudioDeviceMonitor
from app.audio.portaudio_refresh import PortAudioRefreshRequester
from app.audio.protocols import AudioCapture
from app.audio.timeline import AudioTimeline

type Sleep = Callable[[float], Awaitable[None]]
RECOVERY_INITIAL_DELAY_SECONDS = 0.1
RECOVERY_MAX_DELAY_SECONDS = 5.0
RECOVERY_MONITOR_INTERVAL_SECONDS = 0.1
DEFAULT_DEVICE_SETTLE_SECONDS = 0.25

logger = logging.getLogger(__name__)


class CaptureDevice(Protocol):
    """Native input device that can be opened for audio capture."""

    @property
    def index(self) -> int: ...

    @property
    def name(self) -> str: ...

    @property
    def channels(self) -> int: ...

    @property
    def sample_rate(self) -> float: ...


class CaptureDeviceProvider(Protocol):
    """Discover the device used by one capture source."""

    def get_default(self) -> CaptureDevice:
        """Return the currently selected capture device."""


class CaptureDeviceProviderFactory(Protocol):
    """Create a device provider bound to a PyAudio instance."""

    def create(
        self,
        audio: pyaudiowpatch.PyAudio,
    ) -> CaptureDeviceProvider:
        """Create a provider for this PyAudio instance."""


@dataclass(frozen=True, slots=True)
class WasapiInputDevice:
    index: int
    name: str
    channels: int
    sample_rate: float


class WasapiInputDeviceProvider:
    """Discover the current default WASAPI input device."""

    def __init__(self, audio: pyaudiowpatch.PyAudio) -> None:
        self._audio = audio

    def get_default(self) -> CaptureDevice:
        device = self._audio.get_default_wasapi_device(
            d_in=True,
        )

        channels = int(device["maxInputChannels"])
        if channels <= 0:
            raise LookupError(
                "default input device has no input channels",
            )

        return WasapiInputDevice(
            index=int(device["index"]),
            name=str(device["name"]),
            channels=channels,
            sample_rate=float(device["defaultSampleRate"]),
        )


@dataclass(frozen=True, slots=True)
class WasapiLoopbackDevice:
    index: int
    name: str
    channels: int
    sample_rate: float


class WasapiLoopbackDeviceProvider:
    """Discovers the current default WASAPI loopback device."""

    def __init__(self, audio: pyaudiowpatch.PyAudio) -> None:
        self._audio = audio

    def get_default(self) -> CaptureDevice:
        device = self._audio.get_default_wasapi_loopback()

        return WasapiLoopbackDevice(
            index=int(device["index"]),
            name=str(device["name"]),
            channels=int(device["maxInputChannels"]),
            sample_rate=float(device["defaultSampleRate"]),
        )


class PyAudioFactory(Protocol):
    """Create fresh PyAudio instances for capture sessions."""

    def create(self) -> pyaudiowpatch.PyAudio:
        """Create a fresh PyAudio instance."""


class PyAudioFactoryImpl:
    """Production PyAudio factory."""

    def create(self) -> pyaudiowpatch.PyAudio:
        return pyaudiowpatch.PyAudio()


class WasapiLoopbackDeviceProviderFactoryImpl:
    """Production loopback-device-provider factory."""

    def create(
        self,
        audio: pyaudiowpatch.PyAudio,
    ) -> CaptureDeviceProvider:
        return WasapiLoopbackDeviceProvider(audio)


class WasapiInputDeviceProviderFactoryImpl:
    """Production WASAPI input-device-provider factory."""

    def create(
        self,
        audio: pyaudiowpatch.PyAudio,
    ) -> CaptureDeviceProvider:
        return WasapiInputDeviceProvider(audio)


@dataclass(frozen=True, slots=True)
class AudioCaptureStats:
    """Runtime statistics for the capture transport."""

    frames_dropped: int = 0


class QueuedAudioCapture(AudioCapture):
    """Queue-backed asynchronous audio capture boundary.

    A synchronous producer can submit frames without blocking while
    asynchronous consumers receive them through ``frames()``.
    """

    def __init__(self, max_queue_size: int) -> None:
        if max_queue_size <= 0:
            raise ValueError("max_queue_size must be positive")

        self._queue: Queue[AudioFrame | None] = Queue(maxsize=max_queue_size)
        self._state_lock = Lock()
        self._started = False
        self._stopped = False
        self._frames_dropped = 0

        logger.info("max_queue_size=%d", self._queue.maxsize)

    async def start(self) -> None:
        with self._state_lock:
            if self._started:
                return

            self._started = True
            self._stopped = False

    def frames(self) -> AsyncIterator[AudioFrame]:
        return self._frame_stream()

    async def stop(self) -> None:
        with self._state_lock:
            if not self._started or self._stopped:
                return

            self._stopped = True

        self._discard_queued_frames()

        try:
            self._queue.put_nowait(None)
        except Full:
            self._discard_queued_frames()
            self._queue.put_nowait(None)

    def submit(self, frame: AudioFrame) -> bool:
        """Submit a captured frame without blocking.

        Returns ``True`` when the frame was queued and ``False`` when
        the frame was dropped.
        """

        with self._state_lock:
            if not self._started or self._stopped:
                return False

        try:
            self._queue.put_nowait(frame)
        except Full:
            with self._state_lock:
                self._frames_dropped += 1
                frames_dropped = self._frames_dropped

            logger.debug(
                "audio frame dropped frames_dropped=%d",
                frames_dropped,
            )

            return False

        return True

    def stats(self) -> AudioCaptureStats:
        with self._state_lock:
            return AudioCaptureStats(
                frames_dropped=self._frames_dropped,
            )

    def set_discontinuity_handler(
        self,
        handler: Callable[[], None],
    ) -> None:
        return None

    async def _frame_stream(self) -> AsyncIterator[AudioFrame]:
        while True:
            frame = await asyncio.to_thread(self._queue.get)

            if frame is None:
                return

            yield frame

    def _discard_queued_frames(self) -> None:
        while True:
            try:
                self._queue.get_nowait()
            except Exception:
                return


class WasapiAudioFrameFactory:
    """Creates AudioFrames from PyAudio callback data."""

    def __init__(self, audio_format: AudioFormat) -> None:
        self._audio_format = audio_format

    def create(
        self,
        in_data: bytes,
        frame_count: int,
        time_info: dict[str, float],
    ) -> AudioFrame:
        audio = np.frombuffer(in_data, dtype=np.int16).reshape(
            frame_count,
            self._audio_format.channels,
        )

        return AudioFrame(
            audio=audio,
            timestamp=time_info["input_buffer_adc_time"],
            format=self._audio_format,
        )


class PyAudioCapture(AudioCapture):
    def __init__(
        self,
        *,
        audio_factory: PyAudioFactory,
        device_provider_factory: CaptureDeviceProviderFactory,
        device_monitor: AudioDeviceMonitor,
        transport: QueuedAudioCapture,
        timeline: AudioTimeline,
        portaudio_refresh: PortAudioRefreshRequester,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        self._audio_factory = audio_factory
        self._device_provider_factory = device_provider_factory
        self._device_monitor = device_monitor
        self._transport = transport
        self._timeline = timeline
        self._portaudio_refresh = portaudio_refresh
        self._sleep = sleep

        self._audio: pyaudiowpatch.PyAudio | None = None
        self._device_provider: CaptureDeviceProvider | None = None
        self._format: AudioFormat | None = None
        self._stream: pyaudiowpatch.Stream | None = None

        self._lifecycle_task: asyncio.Task[None] | None = None
        self._event_loop: asyncio.AbstractEventLoop | None = None
        self._device_change_event = asyncio.Event()
        self._device_change_generation = 0

        self._started = False
        self._portaudio_timeline_offset: float | None = None
        self._discontinuity_handler: Callable[[], None] | None = None
        self._recovery_active = False
        self._capture_frame_duration_logged = False
        self._portaudio_refresh_active = False

        self._device_monitor.set_change_handler(
            self._handle_default_device_changed,
        )

    async def start(self) -> None:
        if self._started:
            return

        self._started = True
        self._event_loop = asyncio.get_running_loop()

        self._portaudio_timeline_offset = None
        self._recovery_active = False
        self._capture_frame_duration_logged = False
        self._device_change_event.clear()
        self._device_change_generation = 0

        await self._transport.start()

        try:
            self._device_monitor.start()

            with contextlib.suppress(LookupError, OSError):
                await self._open_fresh_stream()

        except Exception:
            self._started = False
            self._event_loop = None

            self._device_monitor.stop()
            self._dispose_audio_session()

            await self._transport.stop()
            raise

        logger.info("audio capture started")

        self._lifecycle_task = asyncio.create_task(
            self._run(),
            name="audio-capture-lifecycle",
        )

    async def stop(self) -> None:
        if not self._started:
            return

        self._started = False

        self._device_monitor.stop()
        self._event_loop = None

        task = self._lifecycle_task
        self._lifecycle_task = None

        if task is not None:
            task.cancel()

            with contextlib.suppress(asyncio.CancelledError):
                await task

        self._dispose_audio_session()

        stats = self._transport.stats()

        logger.info(
            "audio capture stopped frames_dropped=%d",
            stats.frames_dropped,
        )

        await self._transport.stop()

    def frames(self) -> AsyncIterator[AudioFrame]:
        return self._transport.frames()

    def set_discontinuity_handler(
        self,
        handler: Callable[[], None],
    ) -> None:
        """Register the capture discontinuity handler."""
        if self._started:
            raise RuntimeError(
                "discontinuity handler cannot be changed after capture has started",
            )

        self._discontinuity_handler = handler

    def prepare_for_portaudio_refresh(self) -> None:
        if not self._started:
            return

        self._portaudio_refresh_active = True

        self._mark_recovery_started(
            reason="default_device_changed",
        )

        self._dispose_audio_session()

    async def restore_after_portaudio_refresh(self) -> None:
        try:
            if not self._started:
                return

            await self._open_fresh_stream()

            if self._recovery_active:
                logger.info("audio capture recovered")
                self._recovery_active = False
        finally:
            self._portaudio_refresh_active = False

    def _map_portaudio_timestamp(
        self,
        time_info: dict[str, float],
    ) -> float:
        input_time = time_info["input_buffer_adc_time"]
        current_time = time_info["current_time"]

        if self._portaudio_timeline_offset is None:
            self._portaudio_timeline_offset = self._timeline.now() - current_time

        timestamp = input_time + self._portaudio_timeline_offset

        return max(0.0, timestamp)

    async def _open_fresh_stream(self) -> None:
        self._dispose_audio_session()
        self._portaudio_timeline_offset = None

        audio = self._audio_factory.create()
        device_provider = self._device_provider_factory.create(audio)

        try:
            device = device_provider.get_default()

            logger.info(
                "audio capture device selected name=%r index=%d channels=%d sample_rate=%d",
                device.name,
                device.index,
                device.channels,
                int(device.sample_rate),
            )

            audio_format = AudioFormat(
                sample_rate=int(device.sample_rate),
                channels=device.channels,
                sample_type="int16",
            )

            stream = audio.open(
                rate=int(device.sample_rate),
                channels=device.channels,
                format=pyaudiowpatch.paInt16,
                input=True,
                input_device_index=device.index,
                frames_per_buffer=0,
                start=False,
                stream_callback=self._on_audio,
            )

            try:
                stream.start_stream()
            except Exception:
                stream.close()
                raise

        except Exception:
            audio.terminate()
            raise

        self._audio = audio
        self._device_provider = device_provider
        self._format = audio_format
        self._stream = stream

    def _close_stream(self) -> None:
        stream = self._stream
        self._stream = None

        if stream is None:
            return

        try:
            stream.stop_stream()
        finally:
            stream.close()

    def _dispose_audio_session(self) -> None:
        audio = self._audio

        self._audio = None
        self._device_provider = None
        self._format = None

        try:
            self._close_stream()
        finally:
            if audio is not None:
                audio.terminate()

    def _create_frame(
        self,
        *,
        in_data: bytes,
        frame_count: int,
        time_info: dict[str, float],
    ) -> AudioFrame:
        if self._format is None:
            raise RuntimeError("capture format is not initialized")

        audio = np.frombuffer(
            in_data,
            dtype=np.int16,
        ).reshape(
            frame_count,
            self._format.channels,
        )

        timestamp = self._map_portaudio_timestamp(
            time_info,
        )

        return AudioFrame(
            audio=audio,
            timestamp=timestamp,
            format=self._format,
        )

    def _on_audio(
        self,
        in_data: bytes,
        frame_count: int,
        time_info: dict[str, float],
        status_flags: int,
    ) -> tuple[None, int]:
        del status_flags

        if not self._capture_frame_duration_logged:
            if self._format is None:
                raise RuntimeError("capture format is not initialized")

            frame_duration = frame_count / self._format.sample_rate

            logger.info(
                "audio capture frame format frame_count=%d duration=%.3fs",
                frame_count,
                frame_duration,
            )

            self._capture_frame_duration_logged = True

        frame = self._create_frame(
            in_data=in_data,
            frame_count=frame_count,
            time_info=time_info,
        )

        self._transport.submit(frame)

        return None, pyaudiowpatch.paContinue

    async def _run(self) -> None:
        delay = RECOVERY_INITIAL_DELAY_SECONDS

        while self._started:
            if self._device_change_event.is_set():
                self._device_change_event.clear()

                await self._portaudio_refresh.request_refresh()

                continue

            stream = self._stream

            if stream is not None and not stream.is_active():
                logger.warning(
                    "audio capture device became inactive",
                )

                self._begin_recovery(
                    reason="stream_inactive",
                )

                await self._sleep(
                    RECOVERY_MONITOR_INTERVAL_SECONDS,
                )
                continue

            if self._portaudio_refresh_active:
                await self._sleep(
                    RECOVERY_MONITOR_INTERVAL_SECONDS,
                )
                continue

            if self._stream is None:
                if not self._recovery_active:
                    logger.warning(
                        "audio capture recovery started reason=device_unavailable",
                    )
                    self._recovery_active = True

                    handler = self._discontinuity_handler

                    if handler is not None:
                        handler()

                try:
                    await self._open_fresh_stream()

                except (LookupError, OSError) as exc:
                    logger.warning(
                        "audio capture recovery failed; retrying error_type=%s error=%r delay=%.3f",
                        type(exc).__name__,
                        exc,
                        delay,
                    )

                    self._dispose_audio_session()

                    device_changed = await self._wait_for_recovery_retry(
                        delay,
                    )

                    if not device_changed:
                        delay = min(
                            delay * 2,
                            RECOVERY_MAX_DELAY_SECONDS,
                        )

                    continue

                delay = RECOVERY_INITIAL_DELAY_SECONDS

                if self._recovery_active:
                    logger.info("audio capture recovered")
                    self._recovery_active = False

                # A newer Windows endpoint notification arrived while the
                # native session was being rebuilt. Process it immediately
                # rather than waiting for the normal monitor interval.
                if self._device_change_event.is_set():
                    continue

            await self._sleep(
                RECOVERY_MONITOR_INTERVAL_SECONDS,
            )

    def _handle_default_device_changed(
        self,
        endpoint_id: str | None,
    ) -> None:
        logger.info(
            "audio capture default device change signaled endpoint_id=%r",
            endpoint_id,
        )

        loop = self._event_loop

        if loop is None:
            return

        loop.call_soon_threadsafe(
            self._signal_default_device_changed,
        )

    def _signal_default_device_changed(self) -> None:
        if not self._started:
            return

        self._portaudio_refresh.signal_refresh_requested()
        self._device_change_event.set()

    def _mark_recovery_started(
        self,
        *,
        reason: str,
    ) -> None:
        if self._recovery_active:
            return

        logger.warning(
            "audio capture recovery started reason=%s",
            reason,
        )

        self._recovery_active = True

        handler = self._discontinuity_handler

        if handler is not None:
            handler()

    def _begin_recovery(
        self,
        *,
        reason: str,
    ) -> None:
        self._mark_recovery_started(reason=reason)
        self._dispose_audio_session()

    async def _wait_for_recovery_retry(
        self,
        delay: float,
    ) -> bool:
        """Return True when a default-device change interrupted the retry wait."""

        if self._device_change_event.is_set():
            return True

        sleep_task = asyncio.ensure_future(
            self._sleep(delay),
        )
        device_change_task = asyncio.create_task(
            self._device_change_event.wait(),
        )

        try:
            done, _ = await asyncio.wait(
                (
                    sleep_task,
                    device_change_task,
                ),
                return_when=asyncio.FIRST_COMPLETED,
            )

            return device_change_task in done
        finally:
            for task in (
                sleep_task,
                device_change_task,
            ):
                if not task.done():
                    task.cancel()

            await asyncio.gather(
                sleep_task,
                device_change_task,
                return_exceptions=True,
            )
