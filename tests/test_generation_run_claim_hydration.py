"""Transaction-boundary tests for generation-run claim hydration."""

import asyncio
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
    valid_tei,
)

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from episodic.canonical.object_store import ObjectStorePort
    from episodic.generation.draft_script import DraftScriptSource
    from episodic.generation.launcher_support import GenerationSourceLimits


@pytest.mark.asyncio
async def test_claim_commits_before_blocked_hydration(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Allow another unit of work to mutate a claimed run during hydration.

    The patch is applied after the launcher is constructed: the launcher must
    resolve ``source_from_document`` from this module when a run hydrates, as
    it did before the component split.
    """
    run_id, _ = await prepare_pending_run(session_factory)
    hydration_started = asyncio.Event()
    release_hydration = asyncio.Event()
    real_source_from_document = launcher_module.source_from_document

    async def block_source_loading(
        document: SourceDocument,
        object_store: ObjectStorePort | None,
        limits: GenerationSourceLimits | None = None,
        *,
        remaining_aggregate_bytes: int | None = None,
    ) -> DraftScriptSource:
        """Block source hydration after canonical reads have released their UOW."""
        hydration_started.set()
        await release_hydration.wait()
        return await real_source_from_document(
            document,
            object_store,
            limits,
            remaining_aggregate_bytes=remaining_aggregate_bytes,
        )

    run_launcher = launcher(
        session_factory,
        RecordingDraftGenerator(draft_result(valid_tei())),
    )
    monkeypatch.setattr(launcher_module, "source_from_document", block_source_loading)

    await run_launcher.launch(run_id)
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
    finally:
        release_hydration.set()
        await run_launcher.drain()

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        events = await uow.generation_runs.list_events(run_id)
    assert [event.kind for event in events][:2] == [
        "run.started",
        "hydration.observed",
    ], events
