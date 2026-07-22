"""Tests for in-process generation-run launching."""

import typing as typ

import pytest

from episodic.canonical.domain import GenerationRunStatus
from episodic.canonical.generation_quality import QaStatus
from episodic.canonical.storage import SqlAlchemyUnitOfWork
from episodic.generation.draft_script import DraftScriptTransientProviderError
from tests.generation_run_launcher_support import (
    BlockingDraftGenerator,
    FailingDraftGenerator,
    RecordingCostRecorder,
    RecordingDraftGenerator,
    draft_result,
    launcher,
    prepare_pending_run,
    valid_tei,
)

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@pytest.mark.asyncio
async def test_launcher_completes_run_and_records_cost(
    session_factory: object,
) -> None:
    """Successful launches should persist TEI, lifecycle events, and cost usage."""
    factory = typ.cast("async_sessionmaker[AsyncSession]", session_factory)
    run_id, episode_id = await prepare_pending_run(factory)
    cost_recorder = RecordingCostRecorder()
    generator = RecordingDraftGenerator(draft_result(valid_tei()))
    run_launcher = launcher(factory, generator, cost_recorder)

    await run_launcher.launch(run_id)
    await run_launcher.drain()

    async with SqlAlchemyUnitOfWork(factory) as uow:
        run = await uow.generation_runs.get_run(run_id)
        episode = await uow.episodes.get(episode_id)
        events = await uow.generation_runs.list_events(run_id)

    assert run is not None
    assert run.status is GenerationRunStatus.SUCCEEDED
    assert run.current_node == "complete"
    assert episode is not None
    assert episode.tei_xml == valid_tei()
    assert episode.qa_status is QaStatus.SKIPPED
    assert [event.kind for event in events] == [
        "run.started",
        "draft.generated",
        "tei.persisted",
        "run.succeeded",
    ]
    assert generator.requests[0].sources[0].content == "Bridgewater launch source text."
    assert [
        profile.display_name for profile in generator.requests[0].presenter_profiles
    ] == ["Host One", "Guest One"]
    assert [profile.role for profile in generator.requests[0].presenter_profiles] == [
        "host",
        "guest",
    ]
    assert cost_recorder.provider_calls[0].workflow_run_id == str(run_id)
    assert cost_recorder.provider_calls[0].usage == {
        "input_tokens": 10,
        "output_tokens": 20,
    }
    assert cost_recorder.finalized_runs == [(str(run_id), "draft")]


@pytest.mark.asyncio
async def test_launcher_records_provider_failure(
    session_factory: object,
) -> None:
    """Draft-generation provider errors should become failed runs."""
    factory = typ.cast("async_sessionmaker[AsyncSession]", session_factory)
    run_id, _ = await prepare_pending_run(factory)
    run_launcher = launcher(
        factory,
        FailingDraftGenerator(DraftScriptTransientProviderError("try again later")),
    )

    await run_launcher.launch(run_id)
    await run_launcher.drain()

    async with SqlAlchemyUnitOfWork(factory) as uow:
        run = await uow.generation_runs.get_run(run_id)
        events = await uow.generation_runs.list_events(run_id)

    assert run is not None
    assert run.status is GenerationRunStatus.FAILED
    assert run.error_message == "try again later"
    assert run.current_node == "failed"
    assert [event.kind for event in events] == ["run.started", "run.failed"]
    assert events[-1].payload["error_category"] == "provider.transient"


@pytest.mark.asyncio
async def test_launcher_records_invalid_tei_failure(
    session_factory: object,
) -> None:
    """Invalid generated TEI should be recorded as a terminal run failure."""
    factory = typ.cast("async_sessionmaker[AsyncSession]", session_factory)
    run_id, _ = await prepare_pending_run(factory)
    run_launcher = launcher(
        factory, RecordingDraftGenerator(draft_result("<TEI>broken"))
    )

    await run_launcher.launch(run_id)
    await run_launcher.drain()

    async with SqlAlchemyUnitOfWork(factory) as uow:
        run = await uow.generation_runs.get_run(run_id)
        events = await uow.generation_runs.list_events(run_id)

    assert run is not None
    assert run.status is GenerationRunStatus.FAILED
    assert [event.kind for event in events] == [
        "run.started",
        "draft.generated",
        "tei.invalid",
        "run.failed",
    ]
    assert events[-1].payload["error_category"] == "tei.invalid"


@pytest.mark.asyncio
async def test_launcher_uses_detached_unit_of_work(
    session_factory: object,
) -> None:
    """Background launches should keep working after a request UoW closes."""
    factory = typ.cast("async_sessionmaker[AsyncSession]", session_factory)
    run_id, episode_id = await prepare_pending_run(factory)
    run_launcher = launcher(factory, RecordingDraftGenerator(draft_result(valid_tei())))

    async with SqlAlchemyUnitOfWork(factory) as request_uow:
        assert await request_uow.generation_runs.get_run(run_id) is not None

    await run_launcher.launch(run_id)
    await run_launcher.drain()

    async with SqlAlchemyUnitOfWork(factory) as uow:
        run = await uow.generation_runs.get_run(run_id)
        episode = await uow.episodes.get(episode_id)

    assert run is not None
    assert run.status is GenerationRunStatus.SUCCEEDED
    assert episode is not None
    assert episode.tei_xml == valid_tei()


@pytest.mark.asyncio
async def test_launcher_shutdown_marks_running_task_failed(
    session_factory: object,
) -> None:
    """Shutdown should fail a still-running background generation task."""
    factory = typ.cast("async_sessionmaker[AsyncSession]", session_factory)
    run_id, _ = await prepare_pending_run(factory)
    generator = BlockingDraftGenerator()
    run_launcher = launcher(factory, generator)

    await run_launcher.launch(run_id)
    await generator.started.wait()
    await run_launcher.shutdown()

    async with SqlAlchemyUnitOfWork(factory) as uow:
        run = await uow.generation_runs.get_run(run_id)
        events = await uow.generation_runs.list_events(run_id)

    assert run is not None
    assert run.status is GenerationRunStatus.FAILED
    assert run.error_message == "Generation task cancelled during shutdown."
    assert events[-1].kind == "run.failed"
    assert events[-1].payload["error_category"] == "launcher.shutdown"
