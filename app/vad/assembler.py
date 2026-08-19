from __future__ import annotations

from collections import deque
from enum import Enum, auto

import numpy as np

from app.audio.contracts import (
    ProcessingAudioFrame,
    SpeechEnd,
    SpeechSegment,
    SpeechStart,
)
from app.core.config.constants import (
    PROCESSING_FRAME_DURATION_MS,
    PROCESSING_FRAME_DURATION_SECONDS,
)
from app.core.config.models import AudioSegmentationSettings


class _AssemblerState(Enum):
    IDLE = auto()
    SPEAKING = auto()
    POST_ROLL = auto()


class SpeechSegmentAssemblerImpl:
    """Assembles normalized audio frames into speech segments."""

    def __init__(
        self,
        settings: AudioSegmentationSettings,
    ) -> None:
        self._settings = settings
        self._state = _AssemblerState.IDLE

        self._pre_roll_frames: deque[ProcessingAudioFrame] = deque()
        self._segment_frames: list[ProcessingAudioFrame] = []
        self._post_roll_frames = 0

    def process(
        self,
        frame: ProcessingAudioFrame,
        events: tuple[SpeechStart | SpeechEnd, ...],
    ) -> tuple[SpeechSegment, ...]:
        if self._state is _AssemblerState.IDLE:
            return self._process_idle(frame, events)

        if self._state is _AssemblerState.SPEAKING:
            return self._process_speaking(frame, events)

        return self._process_post_roll(frame, events)

    def reset(self) -> None:
        self._clear_state()

    def flush(self) -> tuple[SpeechSegment, ...]:
        self._clear_state()
        return ()

    def _process_idle(
        self,
        frame: ProcessingAudioFrame,
        events: tuple[SpeechStart | SpeechEnd, ...],
    ) -> tuple[SpeechSegment, ...]:
        speech_start = next(
            (event for event in events if isinstance(event, SpeechStart)),
            None,
        )

        if speech_start is None:
            self._add_to_pre_roll(frame)
            return ()

        self._segment_frames = [
            *self._pre_roll_frames,
            frame,
        ]
        self._pre_roll_frames.clear()

        if len(self._segment_frames) >= self._max_segment_frames():
            return self._complete_segment()

        self._state = _AssemblerState.SPEAKING

        return ()

    def _process_speaking(
        self,
        frame: ProcessingAudioFrame,
        events: tuple[SpeechStart | SpeechEnd, ...],
    ) -> tuple[SpeechSegment, ...]:
        self._segment_frames.append(frame)

        if len(self._segment_frames) >= self._max_segment_frames():
            return self._complete_segment(continue_speaking=True)

        speech_end = next(
            (event for event in events if isinstance(event, SpeechEnd)),
            None,
        )

        if speech_end is None:
            return ()

        if self._settings.post_roll_ms == 0:
            return self._complete_segment()

        self._state = _AssemblerState.POST_ROLL
        self._post_roll_frames = 0

        return ()

    def _process_post_roll(
        self,
        frame: ProcessingAudioFrame,
        events: tuple[SpeechStart | SpeechEnd, ...],
    ) -> tuple[SpeechSegment, ...]:
        self._segment_frames.append(frame)

        speech_start = next(
            (event for event in events if isinstance(event, SpeechStart)),
            None,
        )

        if speech_start is not None:
            self._post_roll_frames = 0
            self._state = _AssemblerState.SPEAKING

            if len(self._segment_frames) >= self._max_segment_frames():
                return self._complete_segment(continue_speaking=True)

            return ()

        self._post_roll_frames += 1

        required_frames = self._settings.post_roll_ms // PROCESSING_FRAME_DURATION_MS

        if self._post_roll_frames >= required_frames:
            return self._complete_segment()

        if len(self._segment_frames) >= self._max_segment_frames():
            return self._complete_segment()

        return ()

    def _add_to_pre_roll(self, frame: ProcessingAudioFrame) -> None:
        max_frames = self._settings.pre_roll_ms // PROCESSING_FRAME_DURATION_MS

        if max_frames <= 0:
            return

        self._pre_roll_frames.append(frame)

        while len(self._pre_roll_frames) > max_frames:
            self._pre_roll_frames.popleft()

    def _complete_segment(
        self,
        *,
        continue_speaking: bool = False,
    ) -> tuple[SpeechSegment, ...]:
        audio = np.concatenate(
            [frame.audio for frame in self._segment_frames],
            axis=0,
        )

        first_frame = self._segment_frames[0]
        duration = audio.shape[0] / first_frame.format.sample_rate

        segment = SpeechSegment(
            audio=audio,
            timestamp=first_frame.timestamp,
            duration=duration,
            format=first_frame.format,
        )

        self._segment_frames.clear()
        self._post_roll_frames = 0

        if continue_speaking:
            self._state = _AssemblerState.SPEAKING
        else:
            self._clear_state()

        return (segment,)

    def _max_segment_frames(self) -> int:
        return self._settings.max_duration_seconds * int(1 / PROCESSING_FRAME_DURATION_SECONDS)

    def _clear_state(self) -> None:
        self._state = _AssemblerState.IDLE
        self._pre_roll_frames.clear()
        self._segment_frames.clear()
        self._post_roll_frames = 0
