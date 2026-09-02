from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any

import pyaudiowpatch as pyaudio

REPORT_INTERVAL_SECONDS = 5.0


@dataclass(frozen=True, slots=True)
class TimingSnapshot:
    source: str
    callbacks: int
    captured_audio_seconds: float
    wall_since_first_callback: float
    wall_since_last_callback: float
    last_callback_gap: float
    max_callback_gap: float
    generated_lag: float
    max_generated_lag: float
    portaudio_mapped_lag: float | None
    portaudio_input_elapsed: float | None
    portaudio_current_elapsed: float | None
    status_events: int
    last_status_flags: int


@dataclass(slots=True)
class TimingState:
    source: str
    sample_rate: int
    timeline_origin: float

    lock: threading.Lock = field(
        default_factory=threading.Lock,
    )

    callbacks: int = 0
    captured_audio_seconds: float = 0.0

    first_callback_timeline: float | None = None
    last_callback_timeline: float | None = None

    last_callback_gap: float = 0.0
    max_callback_gap: float = 0.0

    generated_next_timestamp: float | None = None
    generated_lag: float = 0.0
    max_generated_lag: float = 0.0

    portaudio_offset: float | None = None
    first_portaudio_input: float | None = None
    first_portaudio_current: float | None = None

    last_portaudio_input: float | None = None
    last_portaudio_current: float | None = None
    portaudio_mapped_lag: float | None = None

    status_events: int = 0
    last_status_flags: int = 0

    def record(
        self,
        *,
        frame_count: int,
        time_info: dict[str, float],
        status_flags: int,
    ) -> None:
        timeline_now = time.monotonic() - self.timeline_origin

        frame_duration = frame_count / self.sample_rate

        with self.lock:
            if self.first_callback_timeline is None:
                self.first_callback_timeline = timeline_now

            if self.last_callback_timeline is not None:
                callback_gap = timeline_now - self.last_callback_timeline

                self.last_callback_gap = callback_gap
                self.max_callback_gap = max(
                    self.max_callback_gap,
                    callback_gap,
                )

            self.last_callback_timeline = timeline_now

            if self.generated_next_timestamp is None:
                generated_timestamp = max(
                    0.0,
                    timeline_now - frame_duration,
                )
            else:
                generated_timestamp = self.generated_next_timestamp

            generated_end = generated_timestamp + frame_duration

            self.generated_next_timestamp = generated_end

            self.generated_lag = timeline_now - generated_end

            self.max_generated_lag = max(
                self.max_generated_lag,
                self.generated_lag,
            )

            self.captured_audio_seconds += frame_duration

            portaudio_input = time_info.get(
                "input_buffer_adc_time",
            )
            portaudio_current = time_info.get(
                "current_time",
            )

            if portaudio_input is not None and portaudio_current is not None:
                if self.portaudio_offset is None:
                    self.portaudio_offset = timeline_now - portaudio_current

                    self.first_portaudio_input = portaudio_input
                    self.first_portaudio_current = portaudio_current

                self.last_portaudio_input = portaudio_input
                self.last_portaudio_current = portaudio_current

                mapped_timestamp = portaudio_input + self.portaudio_offset

                mapped_end = mapped_timestamp + frame_duration

                self.portaudio_mapped_lag = timeline_now - mapped_end

            if status_flags != 0:
                self.status_events += 1
                self.last_status_flags = status_flags

            self.callbacks += 1

    def snapshot(
        self,
    ) -> TimingSnapshot:
        timeline_now = time.monotonic() - self.timeline_origin

        with self.lock:
            first_callback = self.first_callback_timeline
            last_callback = self.last_callback_timeline

            wall_since_first = 0.0 if first_callback is None else timeline_now - first_callback

            wall_since_last = (
                timeline_now if last_callback is None else timeline_now - last_callback
            )

            input_elapsed = None

            if self.first_portaudio_input is not None and self.last_portaudio_input is not None:
                input_elapsed = self.last_portaudio_input - self.first_portaudio_input

            current_elapsed = None

            if self.first_portaudio_current is not None and self.last_portaudio_current is not None:
                current_elapsed = self.last_portaudio_current - self.first_portaudio_current

            return TimingSnapshot(
                source=self.source,
                callbacks=self.callbacks,
                captured_audio_seconds=(self.captured_audio_seconds),
                wall_since_first_callback=(wall_since_first),
                wall_since_last_callback=(wall_since_last),
                last_callback_gap=(self.last_callback_gap),
                max_callback_gap=(self.max_callback_gap),
                generated_lag=(self.generated_lag),
                max_generated_lag=(self.max_generated_lag),
                portaudio_mapped_lag=(self.portaudio_mapped_lag),
                portaudio_input_elapsed=(input_elapsed),
                portaudio_current_elapsed=(current_elapsed),
                status_events=self.status_events,
                last_status_flags=(self.last_status_flags),
            )


@dataclass(slots=True)
class CaptureHandle:
    audio: pyaudio.PyAudio
    stream: Any
    state: TimingState


def create_callback(
    state: TimingState,
) -> Any:
    def callback(
        in_data: bytes,
        frame_count: int,
        time_info: dict[str, float],
        status_flags: int,
    ) -> tuple[None, int]:
        del in_data

        state.record(
            frame_count=frame_count,
            time_info=time_info,
            status_flags=status_flags,
        )

        return None, pyaudio.paContinue

    return callback


def open_capture(
    *,
    source: str,
    audio: pyaudio.PyAudio,
    device: dict[str, Any],
    timeline_origin: float,
) -> CaptureHandle:
    sample_rate = int(device["defaultSampleRate"])
    channels = int(device["maxInputChannels"])
    device_index = int(device["index"])

    state = TimingState(
        source=source,
        sample_rate=sample_rate,
        timeline_origin=timeline_origin,
    )

    stream = audio.open(
        rate=sample_rate,
        channels=channels,
        format=pyaudio.paInt16,
        input=True,
        input_device_index=device_index,
        frames_per_buffer=0,
        start=False,
        stream_callback=create_callback(state),
    )

    print(
        f"{source}: "
        f"name={device['name']!r} "
        f"index={device_index} "
        f"channels={channels} "
        f"sample_rate={sample_rate}"
    )

    return CaptureHandle(
        audio=audio,
        stream=stream,
        state=state,
    )


def format_optional(
    value: float | None,
) -> str:
    if value is None:
        return "n/a"

    return f"{value:.3f}"


def describe_status_flags(
    flags: int,
) -> str:
    if flags == 0:
        return "none"

    names: list[str] = []

    known_flags = (
        (
            pyaudio.paInputUnderflow,
            "input_underflow",
        ),
        (
            pyaudio.paInputOverflow,
            "input_overflow",
        ),
        (
            pyaudio.paOutputUnderflow,
            "output_underflow",
        ),
        (
            pyaudio.paOutputOverflow,
            "output_overflow",
        ),
    )

    for flag, name in known_flags:
        if flags & flag:
            names.append(name)

    if not names:
        return str(flags)

    return "|".join(names)


def print_snapshot(
    snapshot: TimingSnapshot,
) -> None:
    if snapshot.callbacks == 0:
        print(
            f"{snapshot.source}: callbacks=0 since_start={snapshot.wall_since_last_callback:.3f}s"
        )
        return

    ratio = 0.0

    if snapshot.wall_since_first_callback > 0:
        ratio = snapshot.captured_audio_seconds / snapshot.wall_since_first_callback

    print(
        f"{snapshot.source}: "
        f"callbacks={snapshot.callbacks} "
        f"captured={snapshot.captured_audio_seconds:.3f}s "
        f"wall={snapshot.wall_since_first_callback:.3f}s "
        f"audio_wall_ratio={ratio:.4f} "
        f"since_callback={snapshot.wall_since_last_callback:.3f}s "
        f"callback_gap={snapshot.last_callback_gap:.3f}s "
        f"max_callback_gap={snapshot.max_callback_gap:.3f}s "
        f"generated_lag={snapshot.generated_lag:.3f}s "
        f"max_generated_lag={snapshot.max_generated_lag:.3f}s "
        f"pa_mapped_lag="
        f"{format_optional(snapshot.portaudio_mapped_lag)}s "
        f"pa_input_elapsed="
        f"{format_optional(snapshot.portaudio_input_elapsed)}s "
        f"pa_current_elapsed="
        f"{format_optional(snapshot.portaudio_current_elapsed)}s "
        f"status_events={snapshot.status_events} "
        f"last_status="
        f"{describe_status_flags(snapshot.last_status_flags)}"
    )


def close_capture(
    handle: CaptureHandle,
) -> None:
    try:
        if handle.stream.is_active():
            handle.stream.stop_stream()
    finally:
        try:
            handle.stream.close()
        finally:
            handle.audio.terminate()


def main() -> None:
    timeline_origin = time.monotonic()

    system_audio = pyaudio.PyAudio()
    microphone_audio = pyaudio.PyAudio()

    system_device = system_audio.get_default_wasapi_loopback()

    microphone_device = microphone_audio.get_default_wasapi_device(
        d_in=True,
    )

    system = open_capture(
        source="system_audio",
        audio=system_audio,
        device=system_device,
        timeline_origin=timeline_origin,
    )

    microphone = open_capture(
        source="microphone",
        audio=microphone_audio,
        device=microphone_device,
        timeline_origin=timeline_origin,
    )

    try:
        system.stream.start_stream()
        microphone.stream.start_stream()

        print()
        print("Timing diagnostic started.")
        print("Press Ctrl+C to stop.")
        print()

        while True:
            time.sleep(
                REPORT_INTERVAL_SECONDS,
            )

            print("---")

            print_snapshot(
                system.state.snapshot(),
            )
            print_snapshot(
                microphone.state.snapshot(),
            )

    except KeyboardInterrupt:
        print()
        print("Stopping timing diagnostic...")

    finally:
        close_capture(system)
        close_capture(microphone)


if __name__ == "__main__":
    main()
