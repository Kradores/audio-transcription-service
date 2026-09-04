from __future__ import annotations

import wave
from pathlib import Path

import numpy as np

from app.audio.contracts import SpeechSegment


def save_speech_segment_wav(
    segment: SpeechSegment,
    path: Path,
) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    audio = np.clip(
        segment.audio,
        -1.0,
        1.0,
    )

    pcm16 = (
        audio * np.iinfo(np.int16).max
    ).astype(np.int16)

    with wave.open(
        str(path),
        "wb",
    ) as wav_file:
        wav_file.setnchannels(
            segment.format.channels,
        )
        wav_file.setsampwidth(2)
        wav_file.setframerate(
            segment.format.sample_rate,
        )
        wav_file.writeframes(
            pcm16.tobytes(),
        )