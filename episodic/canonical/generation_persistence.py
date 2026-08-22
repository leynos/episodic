"""Persist canonical state at no-QA draft-generation boundaries.

Services ``materialise_episode_from_ingestion`` and ``persist_draft_script``,
their request types, and typed persistence errors are exported. Callers provide
a ``CanonicalUnitOfWork``; this module never creates or disposes one. A ready
:class:`IngestionJob` becomes a deterministic placeholder: pages load before
locking, reservation and projection commit atomically, and repository results
verify duplicates. ``persist_draft_script`` validates a :class:`DraftScriptResult`,
carries :class:`GenerationRun` provenance through :class:`EpisodeTeiUpdate`,
and persists an optimistic TEI revision without commit or rollback.
"""

import typing as typ
import uuid

import tei_rapporteur as tei

from episodic.canonical.domain import (
    ApprovalState,
    CanonicalEpisode,
    EpisodeStatus,
    EpisodeTeiUpdate,
    IngestionJob,
    IntakeState,
    TeiHeader,
)
from episodic.canonical.entity_protocols import SourceDocumentProjectionResult
from episodic.canonical.generation_persistence_projection import (
    source_document_from_attachment,
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
    SourceCountLimitExceededError,
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
        Open unit of work; commits a successful reservation and projection.
    request
        Materialisation command describing the job and deterministic seams.

    Returns
    -------
    CanonicalEpisode
        Placeholder episode and its deterministic source projections.

    Raises
    ------
    MissingAttachedSourcesError
        If the ready job has no attached sources.
    SourceCountLimitExceededError
        If attached sources exceed ``request.max_source_count``.
    GenerationSourceUploadNotFoundError
        If a source projection references an unavailable upload.
    SourceDocumentProjectionError
        If a duplicate projection cannot be verified after persistence.

    Notes
    -----
    Propagates :class:`IngestionJobNotFoundError` if no ingestion job exists,
    and :class:`IngestionJobNotReadyError` if the job is not ready for
    generation.
    """  # noqa: DOC502  # Typed projection failures propagate through helpers.
    sources = await _list_all_sources(
        uow,
        request.ingestion_job_id,
        max_source_count=request.max_source_count,
    )
    if len(sources) == 0:
        await _load_ready_ingestion_job(
            uow, request.ingestion_job_id, should_lock=False
        )
        raise MissingAttachedSourcesError(request.ingestion_job_id)

    job = await _load_ready_ingestion_job(
        uow, request.ingestion_job_id, should_lock=True
    )

    now = request.clock()
    episode = await _materialise_or_reuse_episode(uow, job, request, now)

    has_duplicate = await _project_source_documents(uow, sources, episode.id, now)
    if has_duplicate:
        await _require_projected_source_documents(uow, sources, episode.id)
    await uow.commit()
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
    await uow.ingestion_jobs.set_target_episode(
        job.id,
        episode_id=episode.id,
        updated_at=now,
    )
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


async def _load_ready_ingestion_job(
    uow: CanonicalUnitOfWork,
    ingestion_job_id: uuid.UUID,
    *,
    should_lock: bool,
) -> IngestionJob:
    """Load a ready ingestion job, optionally retaining its row lock."""
    if should_lock:
        job = await uow.ingestion_jobs.get_for_update(ingestion_job_id)
    else:
        job = await uow.ingestion_jobs.get(ingestion_job_id)
    if job is None:
        raise IngestionJobNotFoundError(str(ingestion_job_id))
    if job.intake_state is not IntakeState.READY_FOR_GENERATION:
        raise IngestionJobNotReadyError(ingestion_job_id)
    return job


async def _list_all_sources(
    uow: CanonicalUnitOfWork,
    ingestion_job_id: uuid.UUID,
    *,
    max_source_count: int,
) -> list[IngestionJobSource]:
    """Read at most one more source than the configured materialisation limit."""
    sources = list(
        await uow.ingestion_job_sources.list_for_job_paged(
            ingestion_job_id,
            limit=max_source_count + 1,
            offset=0,
        )
    )
    if len(sources) > max_source_count:
        raise SourceCountLimitExceededError(ingestion_job_id)
    return sources


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
) -> bool:
    """Persist source projections absent from this episode's job."""
    existing_document_ids = await _projected_source_document_ids(
        uow, sources[0].ingestion_job_id
    )
    had_duplicate = False
    for source in sources:
        document_id = uuid.uuid5(episode_id, str(source.id))
        if document_id in existing_document_ids:
            continue
        upload = await _upload_for_source(uow, source)
        result = await uow.source_documents.add_projection(
            source_document_from_attachment(
                _SourceDocumentProjection(
                    source=source,
                    upload=upload,
                    episode_id=episode_id,
                    document_id=document_id,
                    now=now,
                )
            )
        )
        had_duplicate |= result is SourceDocumentProjectionResult.DUPLICATE
    return had_duplicate


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


def _validate_draft_result(result: DraftScriptResult) -> None:
    """Validate draft result metadata before writing episode TEI."""
    expected_hash = sha256_text(result.tei_xml)
    if result.content_hash != expected_hash:
        raise DraftContentHashMismatchError(expected_hash, result.content_hash)
