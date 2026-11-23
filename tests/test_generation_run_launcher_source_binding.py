"""Tests for the launcher's patchable source binding and claim-stage reads.

``source_from_document`` lived in the launcher module and was resolved while a
run hydrated. The base also read the draft generator and source limits at the
stage that used them. These tests pin those use-time reads at launcher level.
"""

import asyncio
import datetime as dt
import typing as typ
import uuid

import pytest

import episodic.generation.launcher as launcher_module
from episodic.canonical.domain import GenerationRunStatus, SourceDocument
from episodic.canonical.storage import FilesystemObjectStore, SqlAlchemyUnitOfWork
from episodic.generation.launcher_support import GenerationSourceLimits
from tests.generation_run_launcher_support import (
    FailingDraftGenerator,
    RecordingDraftGenerator,
    draft_result,
    launch_and_load_run,
    launcher,
    prepare_pending_run,
    valid_tei,
)
from tests.generation_run_launcher_uow_fakes import BlockingUnitOfWorkFactory

if typ.TYPE_CHECKING:
    from pathlib import Path

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from episodic.canonical.object_store import ObjectStorePort
    from episodic.generation.draft_script import DraftScriptSource
    from episodic.generation.launcher_support import SourceDocumentLoader

_SECOND_DOCUMENT_CREATED_AT = dt.datetime(2026, 6, 24, 13, 0, tzinfo=dt.UTC)


async def _add_second_source_document(
    session_factory: async_sessionmaker[AsyncSession],
    run_id: uuid.UUID,
    *,
    content: str | None,
    source_uri: str,
) -> None:
    """Append a second canonical source document to the run's bundle."""
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        run = await uow.generation_runs.get_run(run_id)
        assert run is not None, f"run {run_id} was not persisted"
        await uow.source_documents.add(
            SourceDocument(
                id=uuid.uuid7(),
                ingestion_job_id=run.source_bundle_id,
                canonical_episode_id=run.episode_id,
                reference_document_revision_id=None,
                source_type="research_brief",
                source_uri=source_uri,
                weight=1.0,
                content_hash="sha256:second",
                metadata={} if content is None else {"content": content},
                created_at=_SECOND_DOCUMENT_CREATED_AT,
            )
        )
        await uow.commit()


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


@pytest.mark.asyncio
async def test_launcher_observes_source_patch_applied_during_claim(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A source patch applied after launch but before hydration must be used."""
    run_id, _ = await prepare_pending_run(session_factory)
    claim_started = asyncio.Event()
    release_claim = asyncio.Event()
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

    run_launcher = launcher(
        session_factory,
        RecordingDraftGenerator(draft_result(valid_tei())),
    )
    run_launcher.uow_factory = BlockingUnitOfWorkFactory(
        lambda: SqlAlchemyUnitOfWork(session_factory),
        {1},
        claim_started,
        release_claim,
    )

    await run_launcher.launch(run_id)
    await asyncio.wait_for(claim_started.wait(), timeout=1)
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


@pytest.mark.asyncio
async def test_launcher_observes_draft_generator_replaced_during_claim(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A draft generator replaced while the claim blocks must generate that run."""
    run_id, _ = await prepare_pending_run(session_factory)
    claim_started = asyncio.Event()
    release_claim = asyncio.Event()
    run_launcher = launcher(
        session_factory,
        FailingDraftGenerator(RuntimeError("original generator must not run")),
    )
    run_launcher.uow_factory = BlockingUnitOfWorkFactory(
        lambda: SqlAlchemyUnitOfWork(session_factory),
        {1},
        claim_started,
        release_claim,
    )
    replacement = RecordingDraftGenerator(draft_result(valid_tei()))

    await run_launcher.launch(run_id)
    await asyncio.wait_for(claim_started.wait(), timeout=1)
    run_launcher.draft_generator = replacement
    release_claim.set()
    await run_launcher.drain()

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        run = await uow.generation_runs.get_run(run_id)
    assert run is not None, f"run {run_id} was not persisted"
    assert run.status is GenerationRunStatus.SUCCEEDED, (
        f"run {run_id} status={run.status}"
    )
    assert replacement.requests, "expected the replacement generator to be used"


@pytest.mark.asyncio
async def test_launcher_observes_source_limits_tightened_during_claim(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Source limits tightened while the claim blocks must bound hydration."""
    run_id, _ = await prepare_pending_run(session_factory)
    claim_started = asyncio.Event()
    release_claim = asyncio.Event()
    run_launcher = launcher(
        session_factory,
        RecordingDraftGenerator(draft_result(valid_tei())),
    )
    run_launcher.uow_factory = BlockingUnitOfWorkFactory(
        lambda: SqlAlchemyUnitOfWork(session_factory),
        {1},
        claim_started,
        release_claim,
    )

    await run_launcher.launch(run_id)
    await asyncio.wait_for(claim_started.wait(), timeout=1)
    run_launcher.source_limits = GenerationSourceLimits(max_source_bytes=1)
    release_claim.set()
    await run_launcher.drain()

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        run = await uow.generation_runs.get_run(run_id)
        events = await uow.generation_runs.list_events(run_id)
    assert run is not None, f"run {run_id} was not persisted"
    assert run.status is GenerationRunStatus.FAILED, (
        f"run {run_id} status={run.status}; events={events!r}"
    )
    assert events[-1].payload["error_category"] == "generation.source_limit", (
        f"run {run_id} final event={events[-1]!r}"
    )


class _BlockingSourceDocumentLoader:
    """Source loader that blocks its first call and records every call."""

    def __init__(self, delegate: SourceDocumentLoader) -> None:
        """Store the real loader and create the coordination events."""
        self._delegate = delegate
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.calls = 0

    async def __call__(
        self,
        document: SourceDocument,
        object_store: ObjectStorePort | None,
        limits: GenerationSourceLimits | None = None,
        *,
        remaining_aggregate_bytes: int | None = None,
    ) -> DraftScriptSource:
        """Block the first call, then delegate to the real loader."""
        self.calls += 1
        if self.calls == 1:
            self.started.set()
            await self.release.wait()
        return await self._delegate(
            document,
            object_store,
            limits,
            remaining_aggregate_bytes=remaining_aggregate_bytes,
        )


@pytest.mark.asyncio
async def test_launcher_reads_source_limits_for_each_document(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A limit tightened during the first load must apply to the second document."""
    run_id, _ = await prepare_pending_run(session_factory)
    await _add_second_source_document(
        session_factory,
        run_id,
        content="Second source text.",
        source_uri="https://example.test/second.md",
    )
    loader = _BlockingSourceDocumentLoader(launcher_module.source_from_document)
    monkeypatch.setattr(launcher_module, "source_from_document", loader)
    run_launcher = launcher(
        session_factory,
        RecordingDraftGenerator(draft_result(valid_tei())),
    )

    await run_launcher.launch(run_id)
    await asyncio.wait_for(loader.started.wait(), timeout=1)
    run_launcher.source_limits = GenerationSourceLimits(max_source_bytes=1)
    loader.release.set()
    await run_launcher.drain()

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        run = await uow.generation_runs.get_run(run_id)
        events = await uow.generation_runs.list_events(run_id)
    assert loader.calls == 2, "expected the second document load to be attempted"
    assert run is not None, f"run {run_id} was not persisted"
    assert run.status is GenerationRunStatus.FAILED, (
        f"run {run_id} status={run.status}; events={events!r}"
    )
    assert events[-1].payload["error_category"] == "generation.source_limit", (
        f"run {run_id} final event={events[-1]!r}"
    )


@pytest.mark.asyncio
async def test_launcher_reads_object_store_for_each_document(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """An object store assigned during the first load must serve later documents."""
    run_id, _ = await prepare_pending_run(session_factory)
    upload = tmp_path / "uploads" / "second"
    upload.parent.mkdir(parents=True)
    upload.write_bytes(b"Second uploaded source.")
    await _add_second_source_document(
        session_factory,
        run_id,
        content=None,
        source_uri="upload:uploads/second",
    )
    loader = _BlockingSourceDocumentLoader(launcher_module.source_from_document)
    monkeypatch.setattr(launcher_module, "source_from_document", loader)
    run_launcher = launcher(
        session_factory,
        RecordingDraftGenerator(draft_result(valid_tei())),
    )

    await run_launcher.launch(run_id)
    await asyncio.wait_for(loader.started.wait(), timeout=1)
    run_launcher.object_store = FilesystemObjectStore(tmp_path)
    loader.release.set()
    await run_launcher.drain()

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        run = await uow.generation_runs.get_run(run_id)
    assert loader.calls == 2, loader.calls
    assert run is not None, f"run {run_id} was not persisted"
    assert run.status is GenerationRunStatus.SUCCEEDED, (
        f"run {run_id} status={run.status}"
    )
