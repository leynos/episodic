"""Tests for the launcher's patchable source-document binding.

``source_from_document`` lived in the launcher module and was resolved while a
run hydrated. These tests pin that patch point at launcher level, including a
patch applied after the run has started but before hydration.
"""

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
    launch_and_load_run,
    launcher,
    prepare_pending_run,
    valid_tei,
)

if typ.TYPE_CHECKING:
    import collections.abc as cabc

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from episodic.canonical.object_store import ObjectStorePort
    from episodic.canonical.unit_of_work_protocols import CanonicalUnitOfWork
    from episodic.generation.draft_script import DraftScriptSource
    from episodic.generation.launcher_support import GenerationSourceLimits


@pytest.mark.asyncio
async def test_launcher_uses_source_from_document_patched_after_construction(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Patching the launcher module's loader after construction must take effect."""
    run_id, _ = await prepare_pending_run(session_factory)
    run_launcher = launcher(
        session_factory,
        RecordingDraftGenerator(draft_result(valid_tei())),
    )
    seen: list[str] = []
    real_source_from_document = launcher_module.source_from_document

    async def recording_source_from_document(
        document: SourceDocument,
        object_store: ObjectStorePort | None,
        limits: GenerationSourceLimits | None = None,
        *,
        remaining_aggregate_bytes: int | None = None,
    ) -> DraftScriptSource:
        """Record the patched call and delegate to the real loader."""
        seen.append(str(document.id))
        return await real_source_from_document(
            document,
            object_store,
            limits,
            remaining_aggregate_bytes=remaining_aggregate_bytes,
        )

    monkeypatch.setattr(
        launcher_module,
        "source_from_document",
        recording_source_from_document,
    )

    run, events = await launch_and_load_run(session_factory, run_id, run_launcher)

    assert run.status is GenerationRunStatus.SUCCEEDED, (
        f"run {run_id} status={run.status}; events={events!r}"
    )
    assert seen, "expected the post-construction patch to load the run's sources"
    assert events[-1].occurred_at >= dt.datetime(2026, 1, 1, tzinfo=dt.UTC), events


class _BlockingUnitOfWork:
    """Unit-of-work proxy that blocks on entry, then delegates to the real UoW."""

    def __init__(
        self,
        factory: cabc.Callable[[], CanonicalUnitOfWork],
        started: asyncio.Event,
        release: asyncio.Event,
    ) -> None:
        """Store the real factory and the coordination events."""
        self._factory = factory
        self._started = started
        self._release = release
        self._inner: CanonicalUnitOfWork | None = None

    async def __aenter__(self) -> CanonicalUnitOfWork:
        """Signal entry, wait for release, then enter the real unit of work."""
        self._started.set()
        await self._release.wait()
        self._inner = self._factory()
        return await self._inner.__aenter__()

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: object,
    ) -> None:
        """Exit the real unit of work."""
        assert self._inner is not None, "unit of work was never entered"
        await self._inner.__aexit__(exc_type, exc, typ.cast("typ.Any", traceback))


@pytest.mark.asyncio
async def test_launcher_observes_source_patch_applied_during_claim(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A source patch applied after launch but before hydration must be used."""
    run_id, _ = await prepare_pending_run(session_factory)
    claim_entered = asyncio.Event()
    release_claim = asyncio.Event()
    seen: list[str] = []
    entered = 0

    def blocking_uow_factory() -> CanonicalUnitOfWork:
        """Return a unit of work whose first entry blocks the claim."""
        nonlocal entered
        entered += 1
        if entered == 1:
            return typ.cast(
                "CanonicalUnitOfWork",
                _BlockingUnitOfWork(
                    lambda: SqlAlchemyUnitOfWork(session_factory),
                    claim_entered,
                    release_claim,
                ),
            )
        return SqlAlchemyUnitOfWork(session_factory)

    real_source_from_document = launcher_module.source_from_document

    async def recording_source_from_document(
        document: SourceDocument,
        object_store: ObjectStorePort | None,
        limits: GenerationSourceLimits | None = None,
        *,
        remaining_aggregate_bytes: int | None = None,
    ) -> DraftScriptSource:
        """Record the patched call and delegate to the real loader."""
        seen.append(str(document.id))
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
    run_launcher.uow_factory = blocking_uow_factory

    await run_launcher.launch(run_id)
    await asyncio.wait_for(claim_entered.wait(), timeout=1)
    monkeypatch.setattr(
        launcher_module,
        "source_from_document",
        recording_source_from_document,
    )
    release_claim.set()
    await run_launcher.drain()

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        run = await uow.generation_runs.get_run(run_id)
    assert run is not None, f"run {run_id} was not persisted"
    assert run.status is GenerationRunStatus.SUCCEEDED, (
        f"run {run_id} status={run.status}"
    )
    assert seen, "expected the patch applied during the claim to load the sources"
