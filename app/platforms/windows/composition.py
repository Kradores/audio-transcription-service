from pathlib import Path

from app.application import Application
from app.audio.protocols import ConversationCaptureFactory, ConversationCaptures
from app.audio.timeline import AudioTimeline
from app.composition import create_application
from app.core.runtime_paths import RuntimePaths
from app.platforms.windows.audio.capture import (
    PyAudioCapture,
    PyAudioFactoryImpl,
    QueuedAudioCapture,
    WasapiInputDeviceProviderFactoryImpl,
    WasapiLoopbackDeviceProviderFactoryImpl,
)
from app.platforms.windows.audio.device_monitor import WindowsAudioDeviceMonitor
from app.platforms.windows.audio.portaudio_refresh import PortAudioRefreshCoordinator
from app.platforms.windows.faster_whisper_runtime import (
    WindowsFasterWhisperRuntimeInitializerFactory,
)


class WindowsConversationCaptureFactory(ConversationCaptureFactory):
    def create(
        self,
        *,
        queue_capacity: int,
        timeline: AudioTimeline,
    ) -> ConversationCaptures:
        portaudio_refresh = PortAudioRefreshCoordinator()

        system_audio = PyAudioCapture(
            audio_factory=PyAudioFactoryImpl(),
            device_provider_factory=WasapiLoopbackDeviceProviderFactoryImpl(),
            device_monitor=WindowsAudioDeviceMonitor(
                flow="eRender",
                role="eConsole",
            ),
            transport=QueuedAudioCapture(
                max_queue_size=queue_capacity,
            ),
            portaudio_refresh=portaudio_refresh,
            timeline=timeline,
        )

        microphone = PyAudioCapture(
            audio_factory=PyAudioFactoryImpl(),
            device_provider_factory=WasapiInputDeviceProviderFactoryImpl(),
            device_monitor=WindowsAudioDeviceMonitor(
                flow="eCapture",
                role="eConsole",
            ),
            transport=QueuedAudioCapture(
                max_queue_size=queue_capacity,
            ),
            portaudio_refresh=portaudio_refresh,
            timeline=timeline,
        )

        portaudio_refresh.register(system_audio)
        portaudio_refresh.register(microphone)

        return ConversationCaptures(
            system_audio=system_audio,
            microphone=microphone,
        )


def create_windows_application(
    runtime_paths: RuntimePaths,
    *,
    nvidia_runtime_directory: Path | None = None,
) -> Application:
    return create_application(
        runtime_paths,
        capture_factory=WindowsConversationCaptureFactory(),
        runtime_initializer_factory=(
            WindowsFasterWhisperRuntimeInitializerFactory(
                nvidia_runtime_directory=nvidia_runtime_directory,
            )
        ),
    )
