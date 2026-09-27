from pathlib import Path
from unittest.mock import ANY, MagicMock, call, patch

from app.application import Application
from app.audio.capture import (
    PyAudioCapture,
    WasapiInputDeviceProviderFactoryImpl,
    WasapiLoopbackDeviceProviderFactoryImpl,
)
from app.audio.timeline import MonotonicAudioTimeline
from app.core.runtime_paths import RuntimePaths
from app.platforms.windows.composition import (
    WindowsConversationCaptureFactory,
    create_windows_application,
)
from app.platforms.windows.faster_whisper_runtime import (
    WindowsFasterWhisperRuntimeInitializerFactory,
)


def test_capture_factory_creates_pyaudio_captures() -> None:
    timeline = MonotonicAudioTimeline()

    captures = WindowsConversationCaptureFactory().create(
        queue_capacity=100,
        timeline=timeline,
    )

    assert isinstance(captures.system_audio, PyAudioCapture)
    assert isinstance(captures.microphone, PyAudioCapture)


def test_capture_factory_uses_loopback_provider_for_system_audio() -> None:
    captures = WindowsConversationCaptureFactory().create(
        queue_capacity=100,
        timeline=MonotonicAudioTimeline(),
    )

    system_capture = captures.system_audio
    assert isinstance(system_capture, PyAudioCapture)

    assert isinstance(
        system_capture._device_provider_factory,
        WasapiLoopbackDeviceProviderFactoryImpl,
    )


def test_capture_factory_uses_input_provider_for_microphone() -> None:
    captures = WindowsConversationCaptureFactory().create(
        queue_capacity=100,
        timeline=MonotonicAudioTimeline(),
    )

    microphone_capture = captures.microphone
    assert isinstance(microphone_capture, PyAudioCapture)

    assert isinstance(
        microphone_capture._device_provider_factory,
        WasapiInputDeviceProviderFactoryImpl,
    )


def test_capture_factory_shares_timeline_between_captures() -> None:
    timeline = MonotonicAudioTimeline()

    captures = WindowsConversationCaptureFactory().create(
        queue_capacity=100,
        timeline=timeline,
    )

    assert isinstance(captures.system_audio, PyAudioCapture)
    assert isinstance(captures.microphone, PyAudioCapture)

    assert captures.system_audio._timeline is timeline
    assert captures.microphone._timeline is timeline


def test_capture_factory_shares_portaudio_refresh_coordinator() -> None:
    captures = WindowsConversationCaptureFactory().create(
        queue_capacity=100,
        timeline=MonotonicAudioTimeline(),
    )

    assert isinstance(captures.system_audio, PyAudioCapture)
    assert isinstance(captures.microphone, PyAudioCapture)

    assert captures.system_audio._portaudio_refresh is captures.microphone._portaudio_refresh


@patch("app.platforms.windows.composition.PortAudioRefreshCoordinator")
def test_capture_factory_registers_both_captures(
    coordinator_type: MagicMock,
) -> None:
    coordinator = coordinator_type.return_value

    captures = WindowsConversationCaptureFactory().create(
        queue_capacity=100,
        timeline=MonotonicAudioTimeline(),
    )

    assert coordinator.register.call_args_list == [
        call(captures.system_audio),
        call(captures.microphone),
    ]


@patch("app.platforms.windows.composition.create_application")
def test_create_windows_application_uses_windows_factories(
    create_application: MagicMock,
) -> None:
    runtime_paths = MagicMock(spec=RuntimePaths)
    application = MagicMock(spec=Application)
    create_application.return_value = application

    result = create_windows_application(runtime_paths)

    assert result is application

    create_application.assert_called_once()

    call_kwargs = create_application.call_args.kwargs

    assert isinstance(
        call_kwargs["capture_factory"],
        WindowsConversationCaptureFactory,
    )
    assert isinstance(
        call_kwargs["runtime_initializer_factory"],
        WindowsFasterWhisperRuntimeInitializerFactory,
    )


@patch("app.platforms.windows.composition.WindowsFasterWhisperRuntimeInitializerFactory")
@patch("app.platforms.windows.composition.create_application")
def test_create_windows_application_passes_nvidia_runtime_directory_to_factory(
    create_application: MagicMock,
    runtime_factory_type: MagicMock,
    tmp_path: Path,
) -> None:
    runtime_paths = MagicMock(spec=RuntimePaths)
    application = MagicMock(spec=Application)
    create_application.return_value = application

    runtime_factory = runtime_factory_type.return_value

    result = create_windows_application(
        runtime_paths,
        nvidia_runtime_directory=tmp_path,
    )

    assert result is application

    runtime_factory_type.assert_called_once_with(
        nvidia_runtime_directory=tmp_path,
    )

    create_application.assert_called_once_with(
        runtime_paths,
        capture_factory=ANY,
        runtime_initializer_factory=runtime_factory,
    )
