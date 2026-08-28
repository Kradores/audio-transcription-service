from __future__ import annotations

import time

import pyaudiowpatch as pyaudio


def describe_defaults(
    label: str,
    audio: pyaudio.PyAudio,
) -> None:
    wasapi = audio.get_host_api_info_by_type(
        pyaudio.paWASAPI,
    )

    output_index = int(wasapi["defaultOutputDevice"])
    input_index = int(wasapi["defaultInputDevice"])

    output = audio.get_device_info_by_index(output_index)
    input_device = audio.get_device_info_by_index(input_index)

    print(
        f"{label}\n"
        f"  output: index={output_index} "
        f"name={output['name']!r}\n"
        f"  input:  index={input_index} "
        f"name={input_device['name']!r}",
        flush=True,
    )


def main() -> None:
    system_audio = pyaudio.PyAudio()
    microphone = pyaudio.PyAudio()

    try:
        print("\nInitial state with TWO PyAudio instances:")
        describe_defaults(
            "system_audio instance",
            system_audio,
        )
        describe_defaults(
            "microphone instance",
            microphone,
        )

        input(
            "\nChange Windows default OUTPUT in Settings, "
            "then press Enter...\n"
        )

        print(
            "\nTerminate/recreate ONLY system_audio PyAudio...",
            flush=True,
        )

        system_audio.terminate()
        time.sleep(0.25)

        system_audio = pyaudio.PyAudio()

        describe_defaults(
            "recreated system_audio instance",
            system_audio,
        )
        describe_defaults(
            "still-alive microphone instance",
            microphone,
        )

        input(
            "\nDO NOT disconnect the headphones.\n"
            "Leave Windows default output on Speakers.\n"
            "Press Enter to terminate BOTH PyAudio instances.\n"
        )

        print(
            "\nNow terminating BOTH PyAudio instances...",
            flush=True,
        )

        system_audio.terminate()
        microphone.terminate()

        time.sleep(0.5)

        system_audio = pyaudio.PyAudio()
        microphone = pyaudio.PyAudio()

        print("\nAfter full PyAudio reset:")

        describe_defaults(
            "system_audio instance",
            system_audio,
        )

        describe_defaults(
            "microphone instance",
            microphone,
        )

    finally:
        system_audio.terminate()
        microphone.terminate()


if __name__ == "__main__":
    main()