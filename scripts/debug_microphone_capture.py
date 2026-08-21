from __future__ import annotations

import asyncio
import contextlib
import logging

from app.audio.timeline import MonotonicAudioTimeline
from app.composition import create_microphone_capture


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )

    timeline = MonotonicAudioTimeline()

    capture = create_microphone_capture(
        queue_capacity=100,
        timeline=timeline,
    )

    frame_count = 0

    try:
        await capture.start()

        print(
            "\nMicrophone capture started.\n"
            "Speak into the microphone.\n"
            "Then change the Windows default input device.\n"
            "Press Ctrl+C to stop.\n",
            flush=True,
        )

        async for frame in capture.frames():
            frame_count += 1

            if frame_count % 50 == 0:
                print(
                    "FRAME "
                    f"count={frame_count} "
                    f"timestamp={frame.timestamp:.3f} "
                    f"sample_rate={frame.format.sample_rate} "
                    f"channels={frame.format.channels} "
                    f"samples={frame.audio.shape[0]}",
                    flush=True,
                )

    finally:
        await capture.stop()

        print(
            f"\nStopped. frames_received={frame_count}",
            flush=True,
        )


if __name__ == "__main__":
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(main())
