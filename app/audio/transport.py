from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from queue import Empty, Full, Queue
from threading import Lock

from app.audio.contracts import AudioFrame


class AudioFrameTransport:
    """Bridges synchronous audio producers and asynchronous consumers."""

    def __init__(self, capacity: int) -> None:
        if capacity <= 0:
            raise ValueError("capacity must be positive")

        self._queue: Queue[AudioFrame | None] = Queue(maxsize=capacity)
        self._lock = Lock()
        self._closed = False
        self._frames_dropped = 0

    @property
    def frames_dropped(self) -> int:
        """Return the number of frames dropped because the queue was full."""

        with self._lock:
            return self._frames_dropped

    def submit(self, frame: AudioFrame) -> bool:
        """Submit a frame without blocking.

        Returns ``True`` when the frame was accepted and ``False`` when
        it was rejected because the transport is closed or full.
        """

        with self._lock:
            if self._closed:
                return False

        try:
            self._queue.put_nowait(frame)
        except Full:
            with self._lock:
                self._frames_dropped += 1

            return False

        return True

    def frames(self) -> AsyncIterator[AudioFrame]:
        """Return an asynchronous stream of transported frames."""

        return self._frame_stream()

    async def close(self) -> None:
        """Discard queued frames and terminate the consumer stream."""

        with self._lock:
            if self._closed:
                return

            self._closed = True

        self._discard_queued_frames()

        # The sentinel wakes a consumer waiting on an empty queue.
        await asyncio.to_thread(self._queue.put, None)

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
            except Empty:
                return
