from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass
from typing import Any

import comtypes
import pyaudiowpatch as pyaudio
from pycaw.callbacks import MMNotificationClient
from pycaw.constants import EDataFlow, ERole
from pycaw.pycaw import AudioUtilities


@dataclass(frozen=True, slots=True)
class CaptureDeviceChange:
    flow: str
    role: str
    device_id: str | None


def describe_pyaudio_device(device: dict[str, Any]) -> str:
    return (
        f"index={device['index']} "
        f"name={device['name']!r} "
        f"sample_rate={device['defaultSampleRate']} "
        f"input_channels={device['maxInputChannels']} "
        f"output_channels={device['maxOutputChannels']} "
        f"host_api={device['hostApi']} "
        f"is_loopback={device.get('isLoopbackDevice')}"
    )


def inspect_core_audio_defaults() -> None:
    enumerator = AudioUtilities.GetDeviceEnumerator()

    print("Windows Core Audio defaults:")

    for role in (
        ERole.eConsole,
        ERole.eMultimedia,
        ERole.eCommunications,
    ):
        device = enumerator.GetDefaultAudioEndpoint(
            EDataFlow.eCapture.value,
            role.value,
        )

        print(
            f"  eCapture / {role.name}: id={device.GetId()!r}",
            flush=True,
        )


def inspect_pyaudio_defaults() -> None:
    print("Creating fresh PyAudio instance...", flush=True)

    audio = pyaudio.PyAudio()

    try:
        print("\nPyAudio global default input:")

        try:
            device = audio.get_default_input_device_info()
        except OSError as exc:
            print(f"  unavailable: {exc!r}")
        else:
            print(f"  {describe_pyaudio_device(device)}")

        print("\nPyAudio WASAPI defaults:")

        try:
            wasapi = audio.get_host_api_info_by_type(
                pyaudio.paWASAPI,
            )
        except OSError as exc:
            print(f"  WASAPI unavailable: {exc!r}")
            return

        print(
            f"  defaultInputDevice={wasapi['defaultInputDevice']}",
            flush=True,
        )
        print(
            f"  defaultOutputDevice={wasapi['defaultOutputDevice']}",
            flush=True,
        )

        default_input_index = int(
            wasapi["defaultInputDevice"],
        )

        if default_input_index >= 0:
            device = audio.get_device_info_by_index(
                default_input_index,
            )

            print(
                "  WASAPI default input:",
                describe_pyaudio_device(device),
                flush=True,
            )

        print("\nAll non-loopback WASAPI input devices:")

        device_count = audio.get_device_count()
        wasapi_host_api_index = int(wasapi["index"])

        for device_index in range(device_count):
            device = audio.get_device_info_by_index(device_index)

            if int(device["hostApi"]) != wasapi_host_api_index:
                continue

            if int(device["maxInputChannels"]) <= 0:
                continue

            if bool(device.get("isLoopbackDevice")):
                continue

            print(
                f"  {describe_pyaudio_device(device)}",
                flush=True,
            )

    finally:
        audio.terminate()
        print("\nPyAudio terminated.", flush=True)


class AudioNotificationClient(MMNotificationClient):
    def __init__(
        self,
        events: queue.Queue[CaptureDeviceChange],
    ) -> None:
        self._events = events

    def on_default_device_changed(
        self,
        flow: str,
        flow_id: int,
        role: str,
        role_id: int,
        default_device_id: str | None,
    ) -> None:
        print(
            "\nNOTIFICATION: "
            f"flow={flow}({flow_id}) "
            f"role={role}({role_id}) "
            f"device_id={default_device_id!r}",
            flush=True,
        )

        if flow != "eCapture":
            return

        self._events.put(
            CaptureDeviceChange(
                flow=flow,
                role=role,
                device_id=default_device_id,
            ),
        )


def inspection_worker(
    events: queue.Queue[CaptureDeviceChange],
    stop_event: threading.Event,
) -> None:
    comtypes.CoInitialize()

    try:
        while not stop_event.is_set():
            try:
                event = events.get(timeout=0.1)
            except queue.Empty:
                continue

            print(
                "\nWORKER: capture default changed "
                f"role={event.role} "
                f"device_id={event.device_id!r}\n",
                flush=True,
            )

            try:
                inspect_core_audio_defaults()
                print()
                inspect_pyaudio_defaults()
            except Exception as exc:
                print(
                    f"WORKER: inspection failed: {exc!r}",
                    flush=True,
                )

    finally:
        comtypes.CoUninitialize()


def main() -> None:
    events: queue.Queue[CaptureDeviceChange] = queue.Queue()
    stop_event = threading.Event()

    enumerator = AudioUtilities.GetDeviceEnumerator()
    client = AudioNotificationClient(events)

    worker = threading.Thread(
        target=inspection_worker,
        args=(events, stop_event),
        name="microphone-device-inspection-worker",
    )

    print("Initial state:\n")

    inspect_core_audio_defaults()
    print()
    inspect_pyaudio_defaults()

    print(
        "\nRegistering Core Audio notification client...",
        flush=True,
    )

    enumerator.RegisterEndpointNotificationCallback(client)
    worker.start()

    print(
        "\nExperiment:\n"
        "  1. Change ONLY the Default Communications microphone.\n"
        "  2. Observe which role notification fires.\n"
        "  3. Observe Core Audio defaults after the change.\n"
        "  4. Observe fresh PyAudio WASAPI defaultInputDevice.\n"
        "  5. Change it back and verify the reverse direction.\n"
        "\nPress Ctrl+C when finished.\n",
        flush=True,
    )

    try:
        while True:
            time.sleep(1)

    except KeyboardInterrupt:
        print("\nStopping...", flush=True)

    finally:
        enumerator.UnregisterEndpointNotificationCallback(client)

        stop_event.set()
        worker.join(timeout=5)

        print("Notification client unregistered.", flush=True)
        print("Worker stopped.", flush=True)


if __name__ == "__main__":
    main()
