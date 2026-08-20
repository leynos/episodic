"""Persist canonical state at the no-QA draft-generation boundaries.

Materialization turns ready jobs into placeholder episodes and source documents.
Persistence validates generator output and applies optimistic TEI updates; the
API materialises before launch, and the detached launcher persists drafts.
"""

import typing as typ
import uuid

import tei_rapporteur as tei
from sqlalchemy.exc import IntegrityError

from episodic.canonical.domain import (
    ApprovalState,
    CanonicalEpisode,
    EpisodeStatus,
    EpisodeTeiUpdate,
    IngestionJob,
    IntakeState,
    SourceDocument,
    TeiHeader,
)
from episodic.canonical.generation_persistence_types import (
    DraftContentHashMismatchError,
    DraftScriptPersistenceError,  # noqa: F401  # Re-exported service contract.
    DraftScriptPersistenceRequest,
    EpisodeMaterialisationRequest,
    GenerationSourceUploadNotFoundError,
    IngestionJobNotReadyError,
    InvalidDraftTeiError,
    MissingAttachedSourcesError,
    SourceDocumentProjectionError,
    _SourceDocumentProjection,
)
from episodic.canonical.generation_quality import QaStatus
from episodic.canonical.hashing import sha256_text
from episodic.canonical.source_intake_errors import IngestionJobNotFoundError
from episodic.canonical.tei import parse_tei_header

if typ.TYPE_CHECKING:
    import datetime as dt

    from episodic.canonical.ingestion_sources import IngestionJobSource
    from episodic.canonical.unit_of_work_protocols import CanonicalUnitOfWork
    from episodic.canonical.uploads import Upload
    from episodic.generation.draft_script import DraftScriptResult


async def materialise_episode_from_ingestion(
    uow: CanonicalUnitOfWork,
    request: EpisodeMaterialisationRequest,
) -> CanonicalEpisode:
    """Materialise a ready ingestion job as a placeholder canonical episode.

    Parameters
    ----------
    uow
        Open unit of work; commits reservation/projection and rolls back races.
    request
        Materialisation command describing the job and deterministic seams.

    Returns
    -------
    CanonicalEpisode
        Placeholder episode reserved before source projection, so retries
        converge on deterministic source-document identifiers.

    Raises
    ------
    IngestionJobNotFoundError
        If no ingestion job exists for the requested identifier.
    IngestionJobNotReadyError
        If the job is not ready for generation.
    MissingAttachedSourcesError
        If the ready job has no attached sources.
    IntegrityError
        If source projection violates an unrelated storage constraint.
    """
    sources = await _list_all_sources(uow, request.ingestion_job_id)
    if len(sources) == 0:
        job = await uow.ingestion_jobs.get(request.ingestion_job_id)
        if job is None:
            raise IngestionJobNotFoundError(str(request.ingestion_job_id))
        if job.intake_state is not IntakeState.READY_FOR_GENERATION:
            raise IngestionJobNotReadyError(request.ingestion_job_id)
        raise MissingAttachedSourcesError(request.ingestion_job_id)

    job = await _get_ingestion_job_for_update(uow, request.ingestion_job_id)
    if job.intake_state is not IntakeState.READY_FOR_GENERATION:
        raise IngestionJobNotReadyError(request.ingestion_job_id)

    now = request.clock()
    episode = await _materialise_or_reuse_episode(uow, job, request, now)

    try:
        await _project_source_documents(uow, sources, episode.id, now)
        await uow.commit()
    except IntegrityError as exc:
        await uow.rollback()
        if not _is_source_document_duplicate(exc):
            raise
        await _require_projected_source_documents(uow, sources, episode.id)
    return episode


async def _materialise_or_reuse_episode(
    uow: CanonicalUnitOfWork,
    job: IngestionJob,
    request: EpisodeMaterialisationRequest,
    now: dt.datetime,
) -> CanonicalEpisode:
    """Reserve and return the ingestion job's canonical episode."""
    episode_id = job.target_episode_id or request.uuid_factory()
    existing_episode = await uow.episodes.get(episode_id)
    if existing_episode is not None:
        await uow.commit()
        return existing_episode

    header = _build_placeholder_header(
        header_id=request.uuid_factory(),
        title=request.title,
        now=now,
    )
    episode = _build_placeholder_episode(
        episode_id=episode_id,
        job=job,
        header=header,
        now=now,
    )
    await uow.tei_headers.add(header)
    await uow.flush()
    await uow.episodes.add(episode)
    await uow.flush()
    await uow.ingestion_jobs.set_target_episode(job.id, episode_id=episode.id)
    # Commit before source projection to limit the ingestion-job row lock.
    await uow.commit()
    return episode


async def persist_draft_script(
    uow: CanonicalUnitOfWork,
    request: DraftScriptPersistenceRequest,
) -> CanonicalEpisode:
    """Persist generated TEI and no-QA provenance onto an episode.

    Parameters
    ----------
    uow
        Open canonical unit of work that owns the revision-guarded update.
    request
        Draft result, episode provenance, expected revision, and clock.

    Returns
    -------
    CanonicalEpisode
        Episode returned by the revision-guarded repository update.

    Raises
    ------
    InvalidDraftTeiError
        If the generated TEI cannot be parsed as a TEI header.

    Notes
    -----
    Hash mismatches and revision conflicts retain their typed domain errors.
    The service does not commit or roll back the unit of work; callers compose
    its episode update with generation-run events and terminal status writes.
    """
    _validate_draft_result(request.result)
    try:
        parse_tei_header(request.result.tei_xml)
    except (TypeError, ValueError) as exc:
        raise InvalidDraftTeiError(str(exc)) from exc
    return await uow.episodes.update(
        request.episode_id,
        update=EpisodeTeiUpdate(
            tei_xml=request.result.tei_xml,
            qa_status=QaStatus.SKIPPED,
            last_generation_run_id=request.generation_run_id,
            expected_revision=request.expected_revision,
            updated_at=request.clock(),
        ),
    )


async def _get_ingestion_job_for_update(
    uow: CanonicalUnitOfWork,
    ingestion_job_id: uuid.UUID,
) -> IngestionJob:
    """Return and lock one ingestion job or raise a not-found error."""
    job = await uow.ingestion_jobs.get_for_update(ingestion_job_id)
    if job is None:
        raise IngestionJobNotFoundError(str(ingestion_job_id))
    return job


async def _list_all_sources(
    uow: CanonicalUnitOfWork,
    ingestion_job_id: uuid.UUID,
) -> list[IngestionJobSource]:
    """List all attached sources for an ingestion job."""
    sources: list[IngestionJobSource] = []
    offset = 0
    page_size = 100
    while True:
        page = await uow.ingestion_job_sources.list_for_job_paged(
            ingestion_job_id,
            limit=page_size,
            offset=offset,
        )
        sources.extend(page)
        if len(page) < page_size:
            return sources
        offset += page_size


async def _projected_source_document_ids(
    uow: CanonicalUnitOfWork,
    ingestion_job_id: uuid.UUID,
) -> set[uuid.UUID]:
    """Return persisted source-document IDs for one ingestion job."""
    documents = await uow.source_documents.list_for_job(ingestion_job_id)
    return {document.id for document in documents}


async def _project_source_documents(
    uow: CanonicalUnitOfWork,
    sources: list[IngestionJobSource],
    episode_id: uuid.UUID,
    now: dt.datetime,
) -> None:
    """Persist source projections absent from this episode's job."""
    existing_document_ids = await _projected_source_document_ids(
        uow, sources[0].ingestion_job_id
    )
    for source in sources:
        document_id = uuid.uuid5(episode_id, str(source.id))
        if document_id in existing_document_ids:
            continue
        upload = await _upload_for_source(uow, source)
        await uow.source_documents.add(
            _source_document_from_attachment(
                _SourceDocumentProjection(
                    source=source,
                    upload=upload,
                    episode_id=episode_id,
                    document_id=document_id,
                    now=now,
                )
            )
        )


async def _require_projected_source_documents(
    uow: CanonicalUnitOfWork,
    sources: list[IngestionJobSource],
    episode_id: uuid.UUID,
) -> None:
    """Verify a duplicate race left every deterministic projection durable."""
    projected_ids = await _projected_source_document_ids(
        uow, sources[0].ingestion_job_id
    )
    expected_ids = {uuid.uuid5(episode_id, str(source.id)) for source in sources}
    missing_ids = expected_ids - projected_ids
    if missing_ids:
        raise SourceDocumentProjectionError(missing_ids)


def _is_source_document_duplicate(error: IntegrityError) -> bool:
    """Return whether a source-document primary-key race caused ``error``."""
    original = error.orig
    constraint_name = getattr(getattr(original, "diag", None), "constraint_name", None)
    if constraint_name == "source_documents_pkey":
        return True
    message = str(original)
    return (
        "source_documents_pkey" in message
        or "UNIQUE constraint failed: source_documents.id" in message
    )


def _build_placeholder_header(
    *,
    header_id: uuid.UUID,
    title: str,
    now: dt.datetime,
) -> TeiHeader:
    """Build a validated placeholder TEI header."""
    tei_xml = _placeholder_tei_xml(title)
    header_payload = parse_tei_header(tei_xml)
    return TeiHeader(
        id=header_id,
        title=header_payload.title,
        payload=header_payload.payload,
        raw_xml=tei_xml,
        created_at=now,
        updated_at=now,
    )


def _placeholder_tei_xml(title: str) -> str:
    """Return minimal valid TEI used before draft generation completes."""
    payload = {
        "header": {"file_desc": {"title": title}},
        "text": {
            "body": {
                "blocks": [
                    {
                        "type": "paragraph",
                        "xml_id": "p-placeholder",
                        "content": [
                            {"type": "text", "value": "Draft generation pending."}
                        ],
                    }
                ]
            }
        },
    }
    document = tei.from_dict(payload)
    document.validate()
    return tei.emit_xml(document)


def _build_placeholder_episode(
    *,
    episode_id: uuid.UUID,
    job: IngestionJob,
    header: TeiHeader,
    now: dt.datetime,
) -> CanonicalEpisode:
    """Build a placeholder canonical episode."""
    return CanonicalEpisode(
        id=episode_id,
        series_profile_id=job.series_profile_id,
        tei_header_id=header.id,
        title=header.title,
        tei_xml=header.raw_xml,
        status=EpisodeStatus.DRAFT,
        approval_state=ApprovalState.DRAFT,
        created_at=now,
        updated_at=now,
    )


async def _upload_for_source(
    uow: CanonicalUnitOfWork,
    source: IngestionJobSource,
) -> Upload | None:
    """Return upload metadata when an attachment points at an upload."""
    if source.upload_id is None:
        return None
    upload = await uow.uploads.get(source.upload_id)
    if upload is None:
        raise GenerationSourceUploadNotFoundError(source.upload_id)
    return upload


def _source_document_from_attachment(
    projection: _SourceDocumentProjection,
) -> SourceDocument:
    """Project an intake source attachment into canonical source metadata."""
    return SourceDocument(
        id=projection.document_id,
        ingestion_job_id=projection.source.ingestion_job_id,
        canonical_episode_id=projection.episode_id,
        reference_document_revision_id=None,
        source_type=projection.source.source_type,
        source_uri=_source_uri(projection.source, projection.upload),
        weight=projection.source.weight,
        content_hash=_source_content_hash(projection.source, projection.upload),
        metadata=projection.source.metadata,
        created_at=projection.now,
    )


def _source_uri(source: IngestionJobSource, upload: Upload | None) -> str:
    """Return a stable source URI for canonical provenance."""
    if source.source_uri is not None:
        return source.source_uri
    if upload is not None:
        return f"upload:{upload.storage_key}"
    return f"upload:{source.upload_id}"


def _source_content_hash(source: IngestionJobSource, upload: Upload | None) -> str:
    """Return the best available source content hash."""
    match source.metadata.get("content_hash"):
        case str() as metadata_hash if metadata_hash.strip():
            return metadata_hash
    if upload is not None and upload.content_hash:
        return upload.content_hash
    return sha256_text(f"{source.source_type}:{_source_uri(source, upload)}")


def _validate_draft_result(result: DraftScriptResult) -> None:
    """Validate draft result metadata before writing episode TEI."""
    expected_hash = sha256_text(result.tei_xml)
    if result.content_hash != expected_hash:
        raise DraftContentHashMismatchError(expected_hash, result.content_hash)
