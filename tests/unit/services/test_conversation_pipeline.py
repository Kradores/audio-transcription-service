import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.conversation_pipeline import ConversationPipeline
from app.services.speech_pipeline import SpeechPipeline
from app.services.transcription_executor import TranscriptionExecutor


def create_executor_mock() -> MagicMock:
    executor = MagicMock(spec=TranscriptionExecutor)
    executor.start = AsyncMock()
    executor.stop = AsyncMock()
    return executor


def create_pipeline_mock() -> MagicMock:
    pipeline = MagicMock(spec=SpeechPipeline)
    pipeline.start = AsyncMock()
    pipeline.stop = AsyncMock()
    return pipeline


@pytest.mark.anyio
async def test_start_starts_executor_before_source_pipelines() -> None:
    # Arrange
    events: list[str] = []

    executor = create_executor_mock()
    system_pipeline = create_pipeline_mock()
    microphone_pipeline = create_pipeline_mock()

    async def start_executor() -> None:
        events.append("executor-start")

    async def start_system() -> None:
        events.append("system-start")

    async def start_microphone() -> None:
        events.append("microphone-start")

    executor.start.side_effect = start_executor
    system_pipeline.start.side_effect = start_system
    microphone_pipeline.start.side_effect = start_microphone

    conversation = ConversationPipeline(
        transcription_executor=executor,
        system_pipeline=system_pipeline,
        microphone_pipeline=microphone_pipeline,
    )

    # Act
    await conversation.start()

    # Assert
    assert events == [
        "executor-start",
        "system-start",
        "microphone-start",
    ]


@pytest.mark.anyio
async def test_stop_stops_sources_before_executor() -> None:
    # Arrange
    events: list[str] = []

    executor = create_executor_mock()
    system_pipeline = create_pipeline_mock()
    microphone_pipeline = create_pipeline_mock()

    async def stop_executor() -> None:
        events.append("executor-stop")

    async def stop_system() -> None:
        events.append("system-stop")

    async def stop_microphone() -> None:
        events.append("microphone-stop")

    executor.stop.side_effect = stop_executor
    system_pipeline.stop.side_effect = stop_system
    microphone_pipeline.stop.side_effect = stop_microphone

    conversation = ConversationPipeline(
        transcription_executor=executor,
        system_pipeline=system_pipeline,
        microphone_pipeline=microphone_pipeline,
    )

    await conversation.start()

    # Act
    await conversation.stop()

    # Assert
    assert events == [
        "system-stop",
        "microphone-stop",
        "executor-stop",
    ]


@pytest.mark.anyio
async def test_start_does_not_start_sources_when_executor_start_fails() -> None:
    # Arrange
    executor = create_executor_mock()
    executor.start.side_effect = RuntimeError("executor failed")

    system_pipeline = create_pipeline_mock()
    microphone_pipeline = create_pipeline_mock()

    conversation = ConversationPipeline(
        transcription_executor=executor,
        system_pipeline=system_pipeline,
        microphone_pipeline=microphone_pipeline,
    )

    # Act / Assert
    with pytest.raises(RuntimeError, match="executor failed"):
        await conversation.start()

    system_pipeline.start.assert_not_awaited()
    microphone_pipeline.start.assert_not_awaited()
    executor.stop.assert_not_awaited()


@pytest.mark.anyio
async def test_start_stops_executor_when_system_pipeline_start_fails() -> None:
    # Arrange
    executor = create_executor_mock()

    system_pipeline = create_pipeline_mock()
    system_pipeline.start.side_effect = RuntimeError("system failed")

    microphone_pipeline = create_pipeline_mock()

    conversation = ConversationPipeline(
        transcription_executor=executor,
        system_pipeline=system_pipeline,
        microphone_pipeline=microphone_pipeline,
    )

    # Act / Assert
    with pytest.raises(RuntimeError, match="system failed"):
        await conversation.start()

    microphone_pipeline.start.assert_not_awaited()
    system_pipeline.stop.assert_not_awaited()
    executor.stop.assert_awaited_once()


@pytest.mark.anyio
async def test_start_rolls_back_system_and_executor_when_microphone_start_fails() -> None:
    # Arrange
    events: list[str] = []

    executor = create_executor_mock()
    system_pipeline = create_pipeline_mock()
    microphone_pipeline = create_pipeline_mock()

    async def stop_system() -> None:
        events.append("system-stop")

    async def stop_executor() -> None:
        events.append("executor-stop")

    microphone_pipeline.start.side_effect = RuntimeError(
        "microphone failed",
    )
    system_pipeline.stop.side_effect = stop_system
    executor.stop.side_effect = stop_executor

    conversation = ConversationPipeline(
        transcription_executor=executor,
        system_pipeline=system_pipeline,
        microphone_pipeline=microphone_pipeline,
    )

    # Act / Assert
    with pytest.raises(RuntimeError, match="microphone failed"):
        await conversation.start()

    assert events == [
        "system-stop",
        "executor-stop",
    ]


@pytest.mark.anyio
async def test_stop_before_start_is_harmless() -> None:
    executor = create_executor_mock()
    system_pipeline = create_pipeline_mock()
    microphone_pipeline = create_pipeline_mock()

    conversation = ConversationPipeline(
        transcription_executor=executor,
        system_pipeline=system_pipeline,
        microphone_pipeline=microphone_pipeline,
    )

    await conversation.stop()

    system_pipeline.stop.assert_not_awaited()
    microphone_pipeline.stop.assert_not_awaited()
    executor.stop.assert_not_awaited()


@pytest.mark.anyio
async def test_wait_propagates_system_pipeline_failure() -> None:
    # Arrange
    executor = create_executor_mock()
    system_pipeline = create_pipeline_mock()
    microphone_pipeline = create_pipeline_mock()

    system_pipeline.wait.side_effect = RuntimeError(
        "system processing failed",
    )

    microphone_blocked = asyncio.Event()

    async def wait_for_microphone() -> None:
        await microphone_blocked.wait()

    microphone_pipeline.wait.side_effect = wait_for_microphone

    conversation = ConversationPipeline(
        transcription_executor=executor,
        system_pipeline=system_pipeline,
        microphone_pipeline=microphone_pipeline,
    )

    # Act / Assert
    with pytest.raises(
        RuntimeError,
        match="system processing failed",
    ):
        await conversation.wait()


@pytest.mark.anyio
async def test_wait_propagates_microphone_pipeline_failure() -> None:
    # Arrange
    executor = create_executor_mock()
    system_pipeline = create_pipeline_mock()
    microphone_pipeline = create_pipeline_mock()

    microphone_pipeline.wait.side_effect = RuntimeError(
        "microphone processing failed",
    )

    system_blocked = asyncio.Event()

    async def wait_for_system() -> None:
        await system_blocked.wait()

    system_pipeline.wait.side_effect = wait_for_system

    conversation = ConversationPipeline(
        transcription_executor=executor,
        system_pipeline=system_pipeline,
        microphone_pipeline=microphone_pipeline,
    )

    # Act / Assert
    with pytest.raises(
        RuntimeError,
        match="microphone processing failed",
    ):
        await conversation.wait()


@pytest.mark.anyio
async def test_wait_rejects_unexpected_source_completion() -> None:
    # Arrange
    executor = create_executor_mock()
    system_pipeline = create_pipeline_mock()
    microphone_pipeline = create_pipeline_mock()

    system_pipeline.wait.return_value = None

    microphone_blocked = asyncio.Event()

    async def wait_for_microphone() -> None:
        await microphone_blocked.wait()

    microphone_pipeline.wait.side_effect = wait_for_microphone

    conversation = ConversationPipeline(
        transcription_executor=executor,
        system_pipeline=system_pipeline,
        microphone_pipeline=microphone_pipeline,
    )

    # Act / Assert
    with pytest.raises(
        RuntimeError,
        match="system_audio",
    ):
        await conversation.wait()
