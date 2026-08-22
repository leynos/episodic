"""Transaction-boundary tests for generation-run claim hydration."""

import asyncio
import contextlib
import datetime as dt
import typing as typ

import pytest

import episodic.generation.launcher as launcher_module
from episodic.canonical.domain import GenerationRunStatus, SourceDocument
from episodic.canonical.storage import SqlAlchemyUnitOfWork
from tests.generation_run_launcher_support import (
    RecordingDraftGenerator,
    draft_result,
    launcher,
    prepare_pending_run,
)

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from episodic.canonical.object_store import ObjectStorePort
    from episodic.generation.launcher_support import GenerationSourceLimits


@pytest.mark.asyncio
async def test_claim_commits_before_blocked_hydration(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Allow another unit of work to mutate a claimed run during hydration."""
    run_id, _ = await prepare_pending_run(session_factory)
    hydration_started = asyncio.Event()
    release_hydration = asyncio.Event()

    original_source_from_document = launcher_module.source_from_document

    async def block_source_loading(
        document: SourceDocument,
        object_store: object,
        limits: object = None,
        *,
        remaining_aggregate_bytes: int | None = None,
    ) -> object:
        """Block source hydration after canonical reads have released their UOW."""
        hydration_started.set()
        await release_hydration.wait()
        return await original_source_from_document(
            document,
            typ.cast("ObjectStorePort | None", object_store),
            typ.cast("GenerationSourceLimits | None", limits),
            remaining_aggregate_bytes=remaining_aggregate_bytes,
        )

    monkeypatch.setattr(launcher_module, "source_from_document", block_source_loading)
    run_launcher = launcher(
        session_factory,
        RecordingDraftGenerator(draft_result("<TEI/>")),
    )
    claim_task = asyncio.create_task(run_launcher._claim(run_id))
    try:
        await asyncio.wait_for(hydration_started.wait(), timeout=1)

        async with SqlAlchemyUnitOfWork(session_factory) as uow:
            claimed_run = await uow.generation_runs.get_run(run_id)
            assert claimed_run is not None, f"expected claimed run {run_id} to persist"
            assert claimed_run.status is GenerationRunStatus.RUNNING, (
                f"expected run {run_id} to be running before hydration, "
                f"got {claimed_run.status.value}"
            )
            await uow.generation_runs.append_event(
                run_id,
                kind="hydration.observed",
                payload={},
                occurred_at=dt.datetime(2026, 8, 20, tzinfo=dt.UTC),
            )
            await uow.commit()

        release_hydration.set()
        claimed = await claim_task
    finally:
        if not release_hydration.is_set():
            release_hydration.set()
        if not claim_task.done():
            claim_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await claim_task

    assert claimed is not None, f"expected claimed run {run_id} after hydration"
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        events = await uow.generation_runs.list_events(run_id)
    assert [event.kind for event in events] == [
        "run.started",
        "hydration.observed",
    ], events
