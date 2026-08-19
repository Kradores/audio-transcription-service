from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass

import pyaudiowpatch as pyaudio
from pycaw.callbacks import MMNotificationClient
from pycaw.pycaw import AudioUtilities

CHUNK_SIZE = 512
WORKER_POLL_SECONDS = 0.1


@dataclass(frozen=True, slots=True)
class DeviceChange:
    device_id: str


def describe_device(device: dict) -> str:
    return (
        f"index={device['index']} "
        f"name={device['name']!r} "
        f"sample_rate={device['defaultSampleRate']} "
        f"channels={device['maxInputChannels']}"
    )


class AudioNotificationClient(MMNotificationClient):
    def __init__(
        self,
        events: queue.Queue[DeviceChange],
    ) -> None:
        self._events = events

    def on_default_device_changed(
        self,
        flow,
        flow_id,
        role,
        role_id,
        default_device_id,
    ) -> None:
        print(
            "NOTIFICATION: "
            f"default device changed "
            f"flow={flow}({flow_id}) "
            f"role={role}({role_id}) "
            f"device_id={default_device_id!r}",
            flush=True,
        )

        # For this experiment we only react once per actual default-output
        # change: render + console.
        if flow != "eRender" or role != "eConsole":
            return

        if default_device_id is None:
            return

        # The callback must remain tiny.
        self._events.put(
            DeviceChange(device_id=default_device_id),
        )

    def on_device_added(self, added_device_id) -> None:
        print(
            f"DEVICE ADDED: {added_device_id!r}",
            flush=True,
        )

    def on_device_removed(self, removed_device_id) -> None:
        print(
            f"DEVICE REMOVED: {removed_device_id!r}",
            flush=True,
        )

    def on_device_state_changed(
        self,
        device_id,
        new_state,
        new_state_id,
    ) -> None:
        print(
            f"DEVICE STATE CHANGED: device_id={device_id!r} state={new_state}({new_state_id})",
            flush=True,
        )


class CaptureWorker:
    def __init__(
        self,
        events: queue.Queue[DeviceChange],
        stop_event: threading.Event,
    ) -> None:
        self._events = events
        self._stop_event = stop_event

        self._pyaudio: pyaudio.PyAudio | None = None
        self._stream = None
        self._device: dict | None = None

        self._callback_count = 0
        self._last_callback = time.monotonic()
        self._callback_lock = threading.Lock()

    def run(self) -> None:
        try:
            self._open_current_default()

            while not self._stop_event.is_set():
                try:
                    event = self._events.get(
                        timeout=WORKER_POLL_SECONDS,
                    )
                except queue.Empty:
                    continue

                print(
                    f"\nWORKER: default-output change received device_id={event.device_id!r}",
                    flush=True,
                )

                self._recover_capture()

        finally:
            self._close_capture()

    def print_status(self) -> None:
        with self._callback_lock:
            callback_count = self._callback_count
            callback_age = time.monotonic() - self._last_callback

        stream = self._stream

        if stream is None:
            active: object = False
            stopped: object = True
        else:
            try:
                active = stream.is_active()
            except Exception as exc:
                active = f"ERROR: {exc!r}"

            try:
                stopped = stream.is_stopped()
            except Exception as exc:
                stopped = f"ERROR: {exc!r}"

        device = self._device

        device_description = "<none>" if device is None else describe_device(device)

        print(
            f"STATUS: callbacks={callback_count:6d} "
            f"last_callback={callback_age:5.2f}s "
            f"active={active!s:5} "
            f"stopped={stopped!s:5} "
            f"device={device_description}",
            flush=True,
        )

    def _callback(
        self,
        in_data: bytes,
        frame_count: int,
        time_info: dict,
        status_flags: int,
    ) -> tuple[bytes, int]:
        del frame_count, time_info

        with self._callback_lock:
            self._callback_count += 1
            self._last_callback = time.monotonic()

        if status_flags:
            print(
                f"CALLBACK STATUS: {status_flags}",
                flush=True,
            )

        return in_data, pyaudio.paContinue

    def _recover_capture(self) -> None:
        print(
            "WORKER: recovering capture...",
            flush=True,
        )

        self._close_capture()

        # Important:
        # give Windows/PortAudio a tiny moment after the Core Audio event
        # before re-enumerating the device graph.
        time.sleep(0.25)

        self._open_current_default()

        print(
            "WORKER: capture recovery complete.",
            flush=True,
        )

    def _open_current_default(self) -> None:
        print(
            "WORKER: creating fresh PyAudio instance...",
            flush=True,
        )

        audio = pyaudio.PyAudio()

        try:
            device = audio.get_default_wasapi_loopback()

            print(
                "WORKER: discovered default loopback:",
                describe_device(device),
                flush=True,
            )

            stream = audio.open(
                format=pyaudio.paInt16,
                channels=int(device["maxInputChannels"]),
                rate=int(device["defaultSampleRate"]),
                frames_per_buffer=CHUNK_SIZE,
                input=True,
                input_device_index=int(device["index"]),
                stream_callback=self._callback,
            )

        except Exception:
            audio.terminate()
            raise

        self._pyaudio = audio
        self._stream = stream
        self._device = device

        print(
            "WORKER: capture stream opened.",
            flush=True,
        )

    def _close_capture(self) -> None:
        stream = self._stream
        audio = self._pyaudio

        self._stream = None
        self._pyaudio = None
        self._device = None

        if stream is not None:
            print(
                "WORKER: closing capture stream...",
                flush=True,
            )

            try:
                if stream.is_active():
                    stream.stop_stream()
            except Exception as exc:
                print(
                    f"WORKER: stop_stream failed: {exc!r}",
                    flush=True,
                )

            try:
                stream.close()
            except Exception as exc:
                print(
                    f"WORKER: stream.close failed: {exc!r}",
                    flush=True,
                )

        if audio is not None:
            print(
                "WORKER: terminating PyAudio...",
                flush=True,
            )

            try:
                audio.terminate()
            except Exception as exc:
                print(
                    f"WORKER: PyAudio termination failed: {exc!r}",
                    flush=True,
                )

        print(
            "WORKER: capture closed.",
            flush=True,
        )


def main() -> None:
    events: queue.Queue[DeviceChange] = queue.Queue()
    stop_event = threading.Event()

    enumerator = AudioUtilities.GetDeviceEnumerator()

    notification_client = AudioNotificationClient(
        events=events,
    )

    capture_worker = CaptureWorker(
        events=events,
        stop_event=stop_event,
    )

    worker_thread = threading.Thread(
        target=capture_worker.run,
        name="wasapi-capture-worker",
    )

    print(
        "Registering Windows Core Audio notification client...",
        flush=True,
    )

    enumerator.RegisterEndpointNotificationCallback(
        notification_client,
    )

    print(
        "Starting capture worker...",
        flush=True,
    )

    worker_thread.start()

    print()
    print("Test sequence:")
    print("  1. Let capture run for a few seconds.")
    print("  2. Headphones -> Speakers.")
    print("  3. Wait 5-10 seconds.")
    print("  4. Speakers -> Headphones.")
    print("  5. Wait 5-10 seconds.")
    print()
    print("Press Ctrl+C to stop.")
    print()

    try:
        while True:
            time.sleep(1)
            capture_worker.print_status()

    except KeyboardInterrupt:
        print(
            "\nStopping...",
            flush=True,
        )

    finally:
        print(
            "Unregistering notification client...",
            flush=True,
        )

        enumerator.UnregisterEndpointNotificationCallback(
            notification_client,
        )

        stop_event.set()

        worker_thread.join(timeout=10)

        if worker_thread.is_alive():
            print(
                "WARNING: capture worker did not stop within timeout.",
                flush=True,
            )
        else:
            print(
                "Capture worker stopped.",
                flush=True,
            )


if __name__ == "__main__":
    main()
