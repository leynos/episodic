"""Tests for in-process generation-run launching."""

import asyncio
import datetime as dt
import typing as typ
import uuid

import pytest

from episodic.canonical.domain import (
    GenerationEvent,
    GenerationRun,
    GenerationRunStatus,
    SourceDocument,
)
from episodic.canonical.generation_quality import QaStatus
from episodic.canonical.storage import FilesystemObjectStore, SqlAlchemyUnitOfWork
from episodic.generation.draft_script import DraftScriptTransientProviderError
from episodic.generation.launcher_support import source_from_document
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
    import collections.abc as cabc
    from pathlib import Path

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from episodic.generation.launcher import InProcessGenerationRunLauncher


async def _uploaded_chunks() -> cabc.AsyncIterator[bytes]:
    """Yield uploaded source bytes with mixed line endings."""
    await asyncio.sleep(0)
    yield b"Uploaded source line one.\r\n"
    yield b"Line two.\n"


async def _launch_and_load_run(
    factory: async_sessionmaker[AsyncSession],
    run_id: uuid.UUID,
    run_launcher: "InProcessGenerationRunLauncher",  # noqa: UP037
) -> tuple[GenerationRun, tuple[GenerationEvent, ...]]:
    """Launch a run and return its persisted terminal state and events."""
    await run_launcher.launch(run_id)
    await run_launcher.drain()
    async with SqlAlchemyUnitOfWork(factory) as uow:
        run = await uow.generation_runs.get_run(run_id)
        events = await uow.generation_runs.list_events(run_id)
    assert run is not None, f"run {run_id} was not persisted; events={events!r}"
    return run, events


@pytest.mark.asyncio
async def test_upload_backed_source_reads_object_content(tmp_path: Path) -> None:
    """Upload provenance should resolve to normalized text before generation."""
    store = FilesystemObjectStore(tmp_path)
    await store.put("uploads/source", _uploaded_chunks(), max_bytes=1_000)
    document = SourceDocument(
        id=uuid.uuid4(),
        ingestion_job_id=uuid.uuid4(),
        canonical_episode_id=uuid.uuid4(),
        reference_document_revision_id=None,
        source_type="research_brief",
        source_uri="upload:uploads/source",
        weight=1.0,
        content_hash="sha256:source",
        metadata={},
        created_at=dt.datetime(2026, 6, 24, tzinfo=dt.UTC),
    )

    source = await source_from_document(document, store)

    assert source.content == "Uploaded source line one.\nLine two.", (
        f"unexpected uploaded source content: {source.content!r}"
    )


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

    assert run is not None, f"run {run_id} was not persisted; events={events!r}"
    assert run.status is GenerationRunStatus.SUCCEEDED, (
        f"run {run_id} status={run.status}; events={events!r}"
    )
    assert run.current_node == "complete", (
        f"run {run_id} current_node={run.current_node!r}"
    )
    assert episode is not None, f"episode {episode_id} was not persisted"
    assert episode.tei_xml == valid_tei(), (
        f"episode {episode_id} TEI={episode.tei_xml!r}"
    )
    assert episode.qa_status is QaStatus.SKIPPED, (
        f"episode {episode_id} qa_status={episode.qa_status!r}"
    )
    assert [event.kind for event in events] == [
        "run.started",
        "draft.generated",
        "tei.persisted",
        "run.succeeded",
    ], f"run {run_id} events={events!r}"
    assert (
        generator.requests[0].sources[0].content == "Bridgewater launch source text."
    ), f"run {run_id} source={generator.requests[0].sources[0]!r}"
    assert [
        profile.display_name for profile in generator.requests[0].presenter_profiles
    ] == ["Host One", "Guest One"], (
        f"run {run_id} profiles={generator.requests[0].presenter_profiles!r}"
    )
    assert [profile.role for profile in generator.requests[0].presenter_profiles] == [
        "host",
        "guest",
    ], f"run {run_id} profiles={generator.requests[0].presenter_profiles!r}"
    assert cost_recorder.provider_calls[0].workflow_run_id == str(run_id), (
        f"run {run_id} provider calls={cost_recorder.provider_calls!r}"
    )
    assert cost_recorder.provider_calls[0].usage == {
        "input_tokens": 10,
        "output_tokens": 20,
    }, f"run {run_id} usage={cost_recorder.provider_calls[0].usage!r}"
    assert cost_recorder.finalized_runs == [(str(run_id), "draft")], (
        f"run {run_id} finalized runs={cost_recorder.finalized_runs!r}"
    )


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

    run, events = await _launch_and_load_run(factory, run_id, run_launcher)

    assert run.status is GenerationRunStatus.FAILED, (
        f"run {run_id} status={run.status}; events={events!r}"
    )
    assert run.error_message == "try again later", (
        f"run {run_id} error={run.error_message!r}"
    )
    assert run.current_node == "failed", (
        f"run {run_id} current_node={run.current_node!r}"
    )
    assert [event.kind for event in events] == ["run.started", "run.failed"], (
        f"run {run_id} events={events!r}"
    )
    assert events[-1].payload["error_category"] == "provider.transient", (
        f"run {run_id} final event={events[-1]!r}"
    )


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

    run, events = await _launch_and_load_run(factory, run_id, run_launcher)

    assert run.status is GenerationRunStatus.FAILED, (
        f"run {run_id} status={run.status}; events={events!r}"
    )
    assert [event.kind for event in events] == [
        "run.started",
        "draft.generated",
        "tei.invalid",
        "run.failed",
    ], f"run {run_id} events={events!r}"
    assert events[-1].payload["error_category"] == "tei.invalid", (
        f"run {run_id} final event={events[-1]!r}"
    )


@pytest.mark.asyncio
async def test_launcher_uses_detached_unit_of_work(
    session_factory: object,
) -> None:
    """Background launches should keep working after a request UoW closes."""
    factory = typ.cast("async_sessionmaker[AsyncSession]", session_factory)
    run_id, episode_id = await prepare_pending_run(factory)
    run_launcher = launcher(factory, RecordingDraftGenerator(draft_result(valid_tei())))

    async with SqlAlchemyUnitOfWork(factory) as request_uow:
        assert await request_uow.generation_runs.get_run(run_id) is not None, (
            f"run {run_id} was unavailable in the request unit of work"
        )

    await run_launcher.launch(run_id)
    await run_launcher.drain()

    async with SqlAlchemyUnitOfWork(factory) as uow:
        run = await uow.generation_runs.get_run(run_id)
        episode = await uow.episodes.get(episode_id)

    assert run is not None, f"run {run_id} was not persisted"
    assert run.status is GenerationRunStatus.SUCCEEDED, (
        f"run {run_id} status={run.status}"
    )
    assert episode is not None, f"episode {episode_id} was not persisted"
    assert episode.tei_xml == valid_tei(), (
        f"episode {episode_id} TEI={episode.tei_xml!r}"
    )


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

    assert run is not None, f"run {run_id} was not persisted; events={events!r}"
    assert run.status is GenerationRunStatus.FAILED, (
        f"run {run_id} status={run.status}; events={events!r}"
    )
    assert run.error_message == "Generation task cancelled during shutdown.", (
        f"run {run_id} error={run.error_message!r}"
    )
    assert events[-1].kind == "run.failed", f"run {run_id} final event={events[-1]!r}"
    assert events[-1].payload["error_category"] == "launcher.shutdown", (
        f"run {run_id} final event={events[-1]!r}"
    )


@pytest.mark.asyncio
async def test_launcher_returns_while_concurrency_slot_is_busy(
    session_factory: object,
) -> None:
    """Scheduling should not wait for an execution semaphore permit."""
    factory = typ.cast("async_sessionmaker[AsyncSession]", session_factory)
    run_id, _ = await prepare_pending_run(factory)
    generator = BlockingDraftGenerator()
    run_launcher = launcher(factory, generator, max_concurrency=1)

    await run_launcher.launch(run_id)
    await generator.started.wait()
    await asyncio.wait_for(run_launcher.launch(uuid.uuid7()), timeout=0.1)

    await run_launcher.shutdown()
