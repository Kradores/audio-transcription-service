from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from queue import Full, Queue
from threading import Lock

import numpy as np
import pyaudiowpatch

from app.audio.contracts import AudioFormat, AudioFrame
from app.audio.protocols import AudioCapture


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
    ) -> None:
        self._audio = audio
        self._device_provider = device_provider
        self._transport = transport
        self._format: AudioFormat | None = None
        self._stream: pyaudiowpatch.Stream | None = None

    async def start(self) -> None:
        if self._stream is not None:
            return

        device_provider = WasapiLoopbackDeviceProvider(self._audio)
        device = device_provider.get_default()

        self._format = AudioFormat(
            sample_rate=int(device.sample_rate),
            channels=device.channels,
            sample_type="int16",
        )

        self._stream = self._audio.open(
            rate=int(device.sample_rate),
            channels=device.channels,
            format=pyaudiowpatch.paInt16,
            input=True,
            input_device_index=device.index,
            frames_per_buffer=0,
            start=False,
            stream_callback=self._on_audio,
        )

        self._stream.start_stream()

    async def stop(self) -> None:
        stream = self._stream

        if stream is not None:
            self._stream = None

            stream.stop_stream()
            stream.close()
            self._audio.terminate()

        await self._transport.stop()

    def frames(self) -> AsyncIterator[AudioFrame]:
        return self._transport.frames()

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
