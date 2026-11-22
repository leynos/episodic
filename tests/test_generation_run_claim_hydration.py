"""Transaction-boundary tests for generation-run claim hydration."""

import asyncio
import contextlib
import datetime as dt
import typing as typ

import pytest

from episodic.canonical.domain import GenerationRunStatus, SourceDocument
from episodic.canonical.storage import SqlAlchemyUnitOfWork
from episodic.generation.launcher_claim import GenerationRunClaimer
from episodic.generation.launcher_support import (
    BoundedSourceLoader,
    GenerationSourceLimits,
)
from tests.generation_run_launcher_support import (
    RecordingDraftGenerator,
    draft_result,
    prepare_pending_run,
)

if typ.TYPE_CHECKING:
    import collections.abc as cabc

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from episodic.generation.draft_script import DraftScriptSource


class _BlockingSourceLoader:
    """Source loader seam that blocks hydration after the claim commits."""

    def __init__(self) -> None:
        """Create the events that coordinate the blocked hydration."""
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def load(
        self,
        documents: cabc.Sequence[SourceDocument],
        limits: GenerationSourceLimits,
    ) -> tuple[DraftScriptSource, ...]:
        """Block until the test releases hydration, then load normally."""
        self.started.set()
        await self.release.wait()
        return await BoundedSourceLoader().load(documents, limits)


@pytest.mark.asyncio
async def test_claim_commits_before_blocked_hydration(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Allow another unit of work to mutate a claimed run during hydration."""
    run_id, _ = await prepare_pending_run(session_factory)
    source_loader = _BlockingSourceLoader()
    claimer = GenerationRunClaimer(
        uow_factory=lambda: SqlAlchemyUnitOfWork(session_factory),
        draft_generator=RecordingDraftGenerator(draft_result("<TEI/>")),
        source_loader=source_loader,
    )

    claim_task = asyncio.create_task(claimer.claim(run_id))
    try:
        await asyncio.wait_for(source_loader.started.wait(), timeout=1)

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

        source_loader.release.set()
        claimed = await claim_task
    finally:
        if not source_loader.release.is_set():
            source_loader.release.set()
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
