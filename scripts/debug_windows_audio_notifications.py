from __future__ import annotations

import queue
import threading
import time

import pyaudiowpatch as pyaudio
from pycaw.callbacks import MMNotificationClient
from pycaw.pycaw import AudioUtilities

POLL_INTERVAL = 0.1


def describe_device(device: dict | None) -> str:
    if device is None:
        return "<none>"

    return (
        f"index={device['index']} "
        f"name={device['name']!r} "
        f"sample_rate={device['defaultSampleRate']} "
        f"channels={device['maxInputChannels']} "
        f"host_api={device['hostApi']} "
        f"is_loopback={device['isLoopbackDevice']}"
    )


def inspect_default_loopback() -> None:
    print("  Worker: creating fresh PyAudio instance...", flush=True)

    p = pyaudio.PyAudio()

    try:
        try:
            device = p.get_default_wasapi_loopback()
        except OSError as exc:
            print(f"  Worker: PyAudio lookup failed: {exc!r}", flush=True)
            return

        print(
            f"  Worker: default loopback = {describe_device(device)}",
            flush=True,
        )
    finally:
        print("  Worker: terminating PyAudio...", flush=True)
        p.terminate()
        print("  Worker: PyAudio terminated.", flush=True)


class AudioNotificationClient(MMNotificationClient):
    def __init__(self, events: queue.Queue[tuple[str, str]]) -> None:
        self._events = events

    def on_default_device_changed(
        self,
        flow,
        flow_id,
        role,
        role_id,
        default_device_id,
    ):
        print(
            "NOTIFICATION CALLBACK: "
            f"DEFAULT DEVICE CHANGED: "
            f"flow={flow}({flow_id}) "
            f"role={role}({role_id}) "
            f"device_id={default_device_id!r}",
            flush=True,
        )

        # IMPORTANT:
        # Do not create/terminate PyAudio here.
        # Just notify the worker.
        if flow == "eRender":
            self._events.put(("default_render_changed", default_device_id))

    def on_device_added(self, added_device_id):
        print(
            f"DEVICE ADDED: {added_device_id!r}",
            flush=True,
        )

    def on_device_removed(self, removed_device_id):
        print(
            f"DEVICE REMOVED: {removed_device_id!r}",
            flush=True,
        )

    def on_device_state_changed(
        self,
        device_id,
        new_state,
        new_state_id,
    ):
        print(
            "DEVICE STATE CHANGED: "
            f"device_id={device_id!r} "
            f"state={new_state}({new_state_id})",
            flush=True,
        )


def notification_worker(
    events: queue.Queue[tuple[str, str]],
    stop_event: threading.Event,
) -> None:
    while not stop_event.is_set():
        try:
            event_type, device_id = events.get(
                timeout=POLL_INTERVAL,
            )
        except queue.Empty:
            continue

        if event_type != "default_render_changed":
            continue

        print(
            f"WORKER: processing default device change: {device_id!r}",
            flush=True,
        )

        try:
            inspect_default_loopback()
        except Exception as exc:
            print(
                f"WORKER: unexpected error: {exc!r}",
                flush=True,
            )


def main() -> None:
    events: queue.Queue[tuple[str, str]] = queue.Queue()
    stop_event = threading.Event()

    enumerator = AudioUtilities.GetDeviceEnumerator()
    client = AudioNotificationClient(events)

    worker = threading.Thread(
        target=notification_worker,
        args=(events, stop_event),
        name="audio-notification-worker",
        daemon=True,
    )

    print("Registering Windows Core Audio notification client...")
    enumerator.RegisterEndpointNotificationCallback(client)

    worker.start()

    print(
        "Listening for audio device notifications.\n"
        "Switch Speakers <-> Headphones.\n"
        "Press Ctrl+C to stop.\n",
        flush=True,
    )

    try:
        while True:
            time.sleep(1)

    except KeyboardInterrupt:
        print("\nStopping...", flush=True)

    finally:
        print("Unregistering notification client...", flush=True)

        enumerator.UnregisterEndpointNotificationCallback(client)

        stop_event.set()
        worker.join(timeout=5)

        print("Notification client unregistered.", flush=True)
        print("Worker stopped.", flush=True)


if __name__ == "__main__":
    main()