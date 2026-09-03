from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import assert_never

from silero_vad import VADIterator, load_silero_vad

from app.application import Application
from app.audio.capture import (
    PyAudioCapture,
    PyAudioFactoryImpl,
    QueuedAudioCapture,
    WasapiInputDeviceProviderFactoryImpl,
    WasapiLoopbackDeviceProviderFactoryImpl,
)
from app.audio.normalizer import AudioNormalizerImpl
from app.audio.portaudio_refresh import PortAudioRefreshCoordinator
from app.audio.protocols import AudioCapture, AudioNormalizer
from app.audio.resampler import SoXRResamplerFactory
from app.audio.timeline import AudioTimeline, MonotonicAudioTimeline
from app.audio.windows_device_monitor import WindowsAudioDeviceMonitor
from app.core.config.constants import DEFAULT_CONFIGURATION_PATH
from app.core.config.enums import WhisperRuntime
from app.core.config.loader import ConfigurationLoader
from app.core.config.models import (
    AdaptiveTranscriptionLanguageSettings,
    AudioProcessingSettings,
    AudioSegmentationSettings,
    AutoTranscriptionLanguageSettings,
    FixedTranscriptionLanguageSettings,
    Settings,
    TranscriptionLanguageSettings,
)
from app.core.logging import configure_logging
from app.services.conversation_pipeline import ConversationPipeline
from app.services.speech_pipeline import SpeechPipeline
from app.services.transcription_executor import TranscriptionExecutor, TranscriptionExecutorImpl
from app.storage.recorder import TranscriptRecorderImpl
from app.storage.sqlite import SQLiteTranscriptRepository
from app.transcription.adaptive_language_state import AdaptiveLanguageStateStore
from app.transcription.adaptive_processor import AdaptiveTranscriptionProcessor
from app.transcription.aggregation import TranscriptionSegmentAggregatorImpl
from app.transcription.contracts import AudioSource
from app.transcription.faster_whisper import FasterWhisperTranscriber
from app.transcription.faster_whisper_factory import FasterWhisperModelFactory
from app.transcription.faster_whisper_runtime import (
    DefaultFasterWhisperRuntimeInitializer,
    FasterWhisperRuntimeInitializer,
    TheRockFasterWhisperRuntimeInitializer,
)
from app.transcription.processor import TranscriptionProcessorImpl
from app.transcription.protocols import (
    Transcriber,
    TranscriptionProcessor,
    TranscriptionSegmentAggregator,
    WhisperModelProtocol,
)
from app.vad.assembler import SpeechSegmentAssemblerImpl
from app.vad.protocols import AudioVad, SpeechSegmentAssembler
from app.vad.silero import SileroVADAdapter


def create_application(
    config_path: Path = DEFAULT_CONFIGURATION_PATH,
) -> Application:
    """Create and configure the application."""

    settings = ConfigurationLoader(config_path).load()
    configure_logging(settings.logging)

    timeline = MonotonicAudioTimeline()

    database_path = settings.database.path
    database_path.parent.mkdir(parents=True, exist_ok=True)
    database = sqlite3.connect(database_path)

    transcription_executor = create_transcription_executor(
        database=database,
        settings=settings,
    )

    portaudio_refresh = PortAudioRefreshCoordinator()

    system_capture = create_system_audio_capture(
        queue_capacity=settings.audio.capture.queue_capacity,
        timeline=timeline,
        portaudio_refresh=portaudio_refresh,
    )
    microphone_capture = create_microphone_capture(
        queue_capacity=settings.audio.capture.queue_capacity,
        timeline=timeline,
        portaudio_refresh=portaudio_refresh,
    )

    portaudio_refresh.register(system_capture)
    portaudio_refresh.register(microphone_capture)

    system_pipeline = create_source_pipeline(
        source=AudioSource.SYSTEM_AUDIO,
        capture=system_capture,
        settings=settings,
        transcription_executor=transcription_executor,
    )

    microphone_pipeline = create_source_pipeline(
        source=AudioSource.MICROPHONE,
        capture=microphone_capture,
        settings=settings,
        transcription_executor=transcription_executor,
    )

    conversation_pipeline = create_conversation_pipeline(
        transcription_executor=transcription_executor,
        system_pipeline=system_pipeline,
        microphone_pipeline=microphone_pipeline,
    )

    return Application(
        settings=settings,
        conversation_pipeline=conversation_pipeline,
        database=database,
    )


def create_conversation_pipeline(
    *,
    transcription_executor: TranscriptionExecutor,
    system_pipeline: SpeechPipeline,
    microphone_pipeline: SpeechPipeline,
) -> ConversationPipeline:
    return ConversationPipeline(
        transcription_executor=transcription_executor,
        system_pipeline=system_pipeline,
        microphone_pipeline=microphone_pipeline,
    )


def create_source_pipeline(
    *,
    source: AudioSource,
    capture: AudioCapture,
    settings: Settings,
    transcription_executor: TranscriptionExecutor,
) -> SpeechPipeline:
    normalizer = create_normalizer(settings.audio.processing)
    vad = create_vad(settings)

    if vad is None:
        raise ValueError("Speech pipeline requires VAD to be enabled")

    assembler = create_speech_assembler(
        settings=settings.audio.segmentation,
    )

    aggregator = TranscriptionSegmentAggregatorImpl(
        settings.transcription.aggregation,
        source=source,
    )

    return create_speech_pipeline(
        source=source,
        capture=capture,
        normalizer=normalizer,
        vad=vad,
        assembler=assembler,
        transcription_segment_aggregator=aggregator,
        transcription_executor=transcription_executor,
    )


def create_system_audio_capture(
    *,
    queue_capacity: int,
    timeline: AudioTimeline,
    portaudio_refresh: PortAudioRefreshCoordinator,
) -> PyAudioCapture:
    """Create Windows system-audio loopback capture."""

    return PyAudioCapture(
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


def create_microphone_capture(
    *,
    queue_capacity: int,
    timeline: AudioTimeline,
    portaudio_refresh: PortAudioRefreshCoordinator,
) -> PyAudioCapture:
    """Create Windows default-microphone capture."""

    return PyAudioCapture(
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


def create_vad(settings: Settings) -> AudioVad | None:
    """Create the configured voice activity detector."""
    if not settings.vad.enabled:
        return None

    if settings.audio.processing.sample_rate != 16_000:
        raise ValueError(
            "Silero VAD requires audio.processing.sample_rate to be 16000",
        )

    model = load_silero_vad()

    iterator = VADIterator(
        model,
        threshold=settings.vad.speech_threshold,
        sampling_rate=settings.audio.processing.sample_rate,
        min_silence_duration_ms=settings.vad.min_silence_duration_ms,
        speech_pad_ms=0,
    )

    return SileroVADAdapter(iterator)


def create_normalizer(settings: AudioProcessingSettings) -> AudioNormalizer:
    """Create the configured Audio Normalizer"""
    resampler_factory = SoXRResamplerFactory()

    return AudioNormalizerImpl(
        settings=settings,
        resampler_factory=resampler_factory,
    )


def create_faster_whisper_runtime_initializer(
    runtime: WhisperRuntime,
) -> FasterWhisperRuntimeInitializer:
    """Create the configured Faster-Whisper runtime initializer."""

    match runtime:
        case WhisperRuntime.DEFAULT:
            return DefaultFasterWhisperRuntimeInitializer()

        case WhisperRuntime.THEROCK:
            return TheRockFasterWhisperRuntimeInitializer()

    assert_never(runtime)


def create_whisper_model(settings: Settings) -> WhisperModelProtocol:
    """Create the configured Faster-Whisper model."""

    runtime_initializer = create_faster_whisper_runtime_initializer(
        settings.whisper.runtime,
    )

    factory = FasterWhisperModelFactory(
        runtime_initializer=runtime_initializer,
    )

    return factory.create(
        model=settings.whisper.model.value,
        device=settings.whisper.device.value,
        compute_type=settings.whisper.compute_type.value,
        worker_count=settings.transcription.worker_count,
    )


def create_transcriber(
    model: WhisperModelProtocol,
) -> Transcriber:
    """Create one Faster-Whisper transcriber around a shared model."""
    return FasterWhisperTranscriber(model)


def create_transcription_processor(
    *,
    transcriber: Transcriber,
    language_settings: TranscriptionLanguageSettings,
    adaptive_state_store: AdaptiveLanguageStateStore | None = None,
) -> TranscriptionProcessor:
    if isinstance(
        language_settings,
        (
            AutoTranscriptionLanguageSettings,
            FixedTranscriptionLanguageSettings,
        ),
    ):
        return TranscriptionProcessorImpl(
            transcriber=transcriber,
            language_settings=language_settings,
        )

    if adaptive_state_store is None:
        raise ValueError("adaptive transcription language mode requires a shared state store")

    return AdaptiveTranscriptionProcessor(
        transcriber=transcriber,
        settings=language_settings,
        state_store=adaptive_state_store,
    )


def create_transcription_executor(
    *,
    database: sqlite3.Connection,
    settings: Settings,
) -> TranscriptionExecutor:
    language_settings = settings.transcription.language

    adaptive_state_store: AdaptiveLanguageStateStore | None = None

    if isinstance(
        language_settings,
        AdaptiveTranscriptionLanguageSettings,
    ):
        adaptive_state_store = AdaptiveLanguageStateStore(
            initial_language=language_settings.initial_language,
        )

    model = create_whisper_model(settings)

    processors = tuple(
        create_transcription_processor(
            transcriber=FasterWhisperTranscriber(model),
            language_settings=settings.transcription.language,
            adaptive_state_store=adaptive_state_store,
        )
        for _ in range(settings.transcription.worker_count)
    )

    repository = SQLiteTranscriptRepository(database)
    repository.initialize()

    recorder = TranscriptRecorderImpl(repository)

    return TranscriptionExecutorImpl(
        processors=processors,
        on_result=recorder.record,
        queue_capacity=settings.transcription.queue_capacity,
    )


def create_speech_assembler(settings: AudioSegmentationSettings) -> SpeechSegmentAssembler:
    return SpeechSegmentAssemblerImpl(
        settings=settings,
    )


def create_speech_pipeline(
    *,
    source: AudioSource,
    capture: AudioCapture,
    normalizer: AudioNormalizer,
    vad: AudioVad,
    assembler: SpeechSegmentAssembler,
    transcription_segment_aggregator: TranscriptionSegmentAggregator,
    transcription_executor: TranscriptionExecutor,
) -> SpeechPipeline:
    """Create the application speech-processing pipeline."""

    return SpeechPipeline(
        source=source,
        capture=capture,
        normalizer=normalizer,
        vad=vad,
        assembler=assembler,
        transcription_segment_aggregator=transcription_segment_aggregator,
        transcription_executor=transcription_executor,
    )
