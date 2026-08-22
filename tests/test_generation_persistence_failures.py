"""Typed failure tests for draft-generation persistence services."""

import dataclasses as dc
import typing as typ
import uuid

import pytest
from sqlalchemy.exc import IntegrityError

from episodic.canonical.domain import IntakeState
from episodic.canonical.generation_persistence import (
    DraftContentHashMismatchError,
    DraftScriptPersistenceRequest,
    EpisodeMaterialisationRequest,
    GenerationSourceUploadNotFoundError,
    IngestionJobNotReadyError,
    MissingAttachedSourcesError,
    SourceDocumentProjectionError,
    _upload_for_source,
    materialise_episode_from_ingestion,
    persist_draft_script,
)
from episodic.canonical.ingestion_sources import AttachmentKind
from episodic.canonical.storage import SqlAlchemyUnitOfWork
from tests.test_generation_persistence import (
    SequentialUuids,
    _clock,
    _draft_result,
    _ingestion_job,
    _persist_materialisation_input,
    _persist_ready_job,
    _run,
    _series_profile,
    _source,
)

if typ.TYPE_CHECKING:
    import collections.abc as cabc

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from episodic.canonical.domain import SourceDocument
    from episodic.canonical.unit_of_work_protocols import CanonicalUnitOfWork


class _MissingUploadRepository:
    """Return no upload for the focused source-resolution failure path."""

    async def get(self, upload_id: uuid.UUID) -> None:
        """Report the requested upload as absent."""
        del upload_id


class _MissingUploadUnitOfWork:
    """Provide the only repository needed by ``_upload_for_source``."""

    uploads = _MissingUploadRepository()


def test_source_document_projection_error_retains_missing_document_ids() -> None:
    """Projection failures should retain immutable missing-row diagnostics."""
    first_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
    second_id = uuid.UUID("00000000-0000-0000-0000-000000000002")

    error = SourceDocumentProjectionError({second_id, first_id})

    assert error.missing_document_ids == (first_id, second_id), (
        f"missing IDs: {error.missing_document_ids!r}"
    )
    assert str(first_id) in str(error), f"projection error: {error!s}"
    assert str(second_id) in str(error), f"projection error: {error!s}"


async def _materialise(
    factory: async_sessionmaker[AsyncSession],
    ingestion_job_id: uuid.UUID,
) -> object:
    """Materialize one episode using deterministic test seams."""
    async with SqlAlchemyUnitOfWork(factory) as uow:
        return await materialise_episode_from_ingestion(
            uow,
            EpisodeMaterialisationRequest(
                ingestion_job_id=ingestion_job_id,
                title="Bridgewater Futures",
                clock=_clock,
                uuid_factory=SequentialUuids(),
            ),
        )


@pytest.mark.asyncio
async def test_materialise_episode_requires_attached_sources(
    session_factory: object,
) -> None:
    """A source-free job raises the source-specific persistence error."""
    factory = typ.cast("async_sessionmaker[AsyncSession]", session_factory)
    job = _ingestion_job(_series_profile().id, None)

    await _persist_materialisation_input(factory, job)
    with pytest.raises(MissingAttachedSourcesError, match="sources") as raised:
        await _materialise(factory, job.id)

    assert raised.value.ingestion_job_id == job.id, (
        f"source-free job id: {raised.value.ingestion_job_id}"
    )


@pytest.mark.asyncio
async def test_materialise_episode_requires_ready_job_before_sources(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A non-ready source-free job reports the readiness failure first."""
    job = _ingestion_job(
        _series_profile().id,
        None,
        intake_state=IntakeState.AWAITING_SOURCES,
    )

    await _persist_materialisation_input(session_factory, job)
    with pytest.raises(IngestionJobNotReadyError, match="not ready") as raised:
        await _materialise(session_factory, job.id)

    assert raised.value.ingestion_job_id == job.id, (
        f"source-free non-ready job id: {raised.value.ingestion_job_id}"
    )


@pytest.mark.asyncio
async def test_materialise_episode_requires_ready_ingestion_job(
    session_factory: object,
) -> None:
    """A non-ready job raises the readiness-specific persistence error."""
    factory = typ.cast("async_sessionmaker[AsyncSession]", session_factory)
    job = _ingestion_job(
        _series_profile().id,
        None,
        intake_state=IntakeState.AWAITING_SOURCES,
    )

    await _persist_materialisation_input(factory, job, source=_source(job.id))
    with pytest.raises(IngestionJobNotReadyError, match="not ready") as raised:
        await _materialise(factory, job.id)

    assert raised.value.ingestion_job_id == job.id, (
        f"non-ready job id: {raised.value.ingestion_job_id}"
    )


@pytest.mark.asyncio
async def test_source_upload_resolution_rejects_missing_upload() -> None:
    """A missing source upload raises a typed source-resolution error."""
    job = _ingestion_job(_series_profile().id, None)
    upload_id = uuid.UUID("00000000-0000-0000-0000-000000000601")
    source = dc.replace(
        _source(job.id),
        attachment_kind=AttachmentKind.UPLOAD,
        upload_id=upload_id,
        source_uri=None,
    )

    with pytest.raises(GenerationSourceUploadNotFoundError) as raised:
        await _upload_for_source(
            typ.cast("CanonicalUnitOfWork", _MissingUploadUnitOfWork()),
            source,
        )

    assert raised.value.upload_id == upload_id, (
        f"missing upload id: {raised.value.upload_id}"
    )


@pytest.mark.asyncio
async def test_persist_draft_script_rejects_mismatched_content_hash(
    session_factory: object,
) -> None:
    """Generated TEI requires a matching declared content hash."""
    factory = typ.cast("async_sessionmaker[AsyncSession]", session_factory)
    _, job = await _persist_ready_job(factory)
    tei_xml = (
        '<TEI xmlns="http://www.tei-c.org/ns/1.0">'
        "<teiHeader><fileDesc><title>Bridgewater Futures</title></fileDesc></teiHeader>"
        '<text><body><u who="Host">Welcome.</u></body></text></TEI>'
    )

    async with SqlAlchemyUnitOfWork(factory) as uow:
        episode = await materialise_episode_from_ingestion(
            uow,
            EpisodeMaterialisationRequest(
                ingestion_job_id=job.id,
                title="Bridgewater Futures",
                clock=_clock,
                uuid_factory=SequentialUuids(),
            ),
        )
        run = _run(episode.id, job.id)
        await uow.generation_runs.create_run(run)
        result = dc.replace(_draft_result(tei_xml), content_hash="sha256:wrong")
        with pytest.raises(DraftContentHashMismatchError) as raised:
            await persist_draft_script(
                uow,
                DraftScriptPersistenceRequest(
                    episode_id=episode.id,
                    generation_run_id=run.id,
                    result=result,
                    expected_revision=episode.tei_revision,
                    clock=_clock,
                ),
            )

    assert raised.value.expected_hash != raised.value.actual_hash, (
        f"hashes: {raised.value.expected_hash!r}, {raised.value.actual_hash!r}"
    )


@pytest.mark.asyncio
async def test_materialise_reraises_unrelated_projection_integrity_error(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only a source-document duplicate may be recovered as a retry race."""
    _, job = await _persist_ready_job(session_factory)

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        original_commit = uow.commit
        commit_count = 0

        async def fail_projection_commit() -> None:
            """Raise an integrity error only for the projection transaction."""
            nonlocal commit_count
            commit_count += 1
            if commit_count == 2:
                error = ValueError("bad FK")
                raise IntegrityError("", {}, error)
            await original_commit()

        monkeypatch.setattr(uow, "commit", fail_projection_commit)
        with pytest.raises(IntegrityError, match="bad FK"):
            await materialise_episode_from_ingestion(
                uow,
                EpisodeMaterialisationRequest(
                    ingestion_job_id=job.id,
                    title="Bridgewater Futures",
                    clock=_clock,
                    uuid_factory=SequentialUuids(),
                ),
            )

    assert commit_count == 2, f"unexpected commit count: {commit_count}"


@pytest.mark.asyncio
async def test_materialise_verifies_duplicate_projection_rows(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A duplicate race succeeds only after all deterministic rows are found."""
    _, job = await _persist_ready_job(session_factory)
    request = EpisodeMaterialisationRequest(
        ingestion_job_id=job.id,
        title="Bridgewater Futures",
        clock=_clock,
        uuid_factory=SequentialUuids(),
    )

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        first = await materialise_episode_from_ingestion(uow, request)

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        original_list = uow.source_documents.list_for_job
        list_count = 0

        async def hide_existing_projection(
            job_id: uuid.UUID,
        ) -> cabc.Sequence[SourceDocument]:
            """Simulate a concurrent transaction's stale pre-insert read."""
            nonlocal list_count
            list_count += 1
            if list_count == 1:
                return ()
            return await original_list(job_id)

        monkeypatch.setattr(
            uow.source_documents,
            "list_for_job",
            hide_existing_projection,
        )
        second = await materialise_episode_from_ingestion(uow, request)

    assert second.id == first.id, f"duplicate projection episode: {second.id}"
    assert list_count == 2, (
        f"expected projection and verification reads, got {list_count}"
    )
