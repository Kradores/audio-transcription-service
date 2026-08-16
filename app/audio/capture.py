from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from queue import Full, Queue
from threading import Lock

import numpy as np
import pyaudiowpatch

from app.audio.contracts import AudioFormat, AudioFrame
from app.audio.protocols import AudioCapture

type Sleep = Callable[[float], Awaitable[None]]
RECOVERY_INITIAL_DELAY_SECONDS = 0.1
RECOVERY_MAX_DELAY_SECONDS = 5.0
RECOVERY_MONITOR_INTERVAL_SECONDS = 0.1


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

    def get_default(self) -> WasapiLoopbackDevice:
        device = self._audio.get_default_wasapi_loopback()

        return WasapiLoopbackDevice(
            index=int(device["index"]),
            name=str(device["name"]),
            channels=int(device["maxInputChannels"]),
            sample_rate=float(device["defaultSampleRate"]),
        )


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
        audio: pyaudiowpatch.PyAudio,
        device_provider: WasapiLoopbackDeviceProvider,
        transport: QueuedAudioCapture,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        self._audio = audio
        self._device_provider = device_provider
        self._transport = transport
        self._format: AudioFormat | None = None
        self._stream: pyaudiowpatch.Stream | None = None
        self._lifecycle_task: asyncio.Task[None] | None = None
        self._started = False
        self._sleep = sleep
        self._discontinuity_handler: Callable[[], None] | None = None

    async def start(self) -> None:
        if self._started:
            return

        self._started = True
        await self._transport.start()

        try:
            await self._open_stream()
        except LookupError:
            pass
        except Exception:
            self._started = False
            await self._transport.stop()
            self._audio.terminate()
            raise

        self._lifecycle_task = asyncio.create_task(
            self._run(),
            name="audio-capture-lifecycle",
        )

    async def stop(self) -> None:
        if not self._started:
            return

        self._started = False

        task = self._lifecycle_task
        self._lifecycle_task = None

        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

        self._close_stream()

        self._audio.terminate()

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

    async def _open_stream(self) -> None:
        device = self._device_provider.get_default()

        audio_format = AudioFormat(
            sample_rate=int(device.sample_rate),
            channels=device.channels,
            sample_type="int16",
        )

        stream = self._audio.open(
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

    def _create_frame(
        self,
        in_data: bytes,
        frame_count: int,
        time_info: dict[str, float],
    ) -> AudioFrame:
        if self._format is None:
            raise RuntimeError("capture format is not initialized")

        audio = np.frombuffer(in_data, dtype=np.int16).reshape(
            frame_count,
            self._format.channels,
        )

        return AudioFrame(
            audio=audio,
            timestamp=time_info["input_buffer_adc_time"],
            format=self._format,
        )

    def _on_audio(
        self,
        in_data: bytes,
        frame_count: int,
        time_info: dict[str, float],
        status_flags: int,
    ) -> tuple[None, int]:
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
            if self._stream is None:
                try:
                    await self._open_stream()
                except LookupError:
                    await asyncio.sleep(delay)
                    delay = min(
                        delay * 2,
                        RECOVERY_MAX_DELAY_SECONDS,
                    )
                    continue

                delay = RECOVERY_INITIAL_DELAY_SECONDS

            stream = self._stream

            if stream is None:
                continue

            if not stream.is_active():
                self._close_stream()

                handler = self._discontinuity_handler
                if handler is not None:
                    handler()

                continue

            await asyncio.sleep(
                RECOVERY_MONITOR_INTERVAL_SECONDS,
            )
