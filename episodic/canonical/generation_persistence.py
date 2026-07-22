"""Persistence services for draft-generation output."""

import collections.abc as cabc
import dataclasses as dc
import datetime as dt
import hashlib
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
    SourceDocument,
    TeiHeader,
)
from episodic.canonical.generation_quality import QaStatus
from episodic.canonical.source_intake_errors import IngestionJobNotFoundError
from episodic.canonical.tei import parse_tei_header

if typ.TYPE_CHECKING:
    from episodic.canonical.ingestion_sources import IngestionJobSource
    from episodic.canonical.unit_of_work_protocols import CanonicalUnitOfWork
    from episodic.canonical.uploads import Upload
    from episodic.generation.draft_script import DraftScriptResult

Clock = cabc.Callable[[], dt.datetime]
UuidFactory = cabc.Callable[[], uuid.UUID]


def _utc_now() -> dt.datetime:
    """Return a timezone-aware UTC timestamp."""
    return dt.datetime.now(dt.UTC)


def _uuid7() -> uuid.UUID:
    """Return a monotonic storage UUID."""
    return uuid.uuid7()


class DraftScriptPersistenceError(Exception):
    """Base class for draft persistence failures."""


class InvalidDraftTeiError(DraftScriptPersistenceError, ValueError):
    """Raised when generated TEI cannot be validated."""


@dc.dataclass(frozen=True, slots=True)
class EpisodeMaterialisationRequest:
    """Command for materialising an episode from an ingestion job."""

    ingestion_job_id: uuid.UUID
    title: str
    clock: Clock = _utc_now
    uuid_factory: UuidFactory = _uuid7


@dc.dataclass(frozen=True, slots=True)
class DraftScriptPersistenceRequest:
    """Command for writing generated draft TEI to an episode."""

    episode_id: uuid.UUID
    generation_run_id: uuid.UUID
    result: DraftScriptResult
    expected_revision: int
    clock: Clock = _utc_now


@dc.dataclass(frozen=True, slots=True)
class _SourceDocumentProjection:
    source: IngestionJobSource
    upload: Upload | None
    episode_id: uuid.UUID
    now: dt.datetime
    uuid_factory: UuidFactory


async def materialise_episode_from_ingestion(
    uow: CanonicalUnitOfWork,
    request: EpisodeMaterialisationRequest,
) -> CanonicalEpisode:
    """Create a placeholder canonical episode for a ready ingestion job."""
    job = await _get_ingestion_job_for_update(uow, request.ingestion_job_id)
    if job.intake_state is not IntakeState.READY_FOR_GENERATION:
        msg = f"Ingestion job {request.ingestion_job_id} is not ready for generation."
        raise DraftScriptPersistenceError(msg)

    episode_id = job.target_episode_id or request.uuid_factory()
    existing_episode = await uow.episodes.get(episode_id)
    if existing_episode is not None:
        return existing_episode

    sources = await _list_all_sources(uow, request.ingestion_job_id)
    if len(sources) == 0:
        msg = f"Ingestion job {request.ingestion_job_id} has no attached sources."
        raise DraftScriptPersistenceError(msg)

    now = request.clock()
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
    for source in sources:
        upload = await _upload_for_source(uow, source)
        await uow.source_documents.add(
            _source_document_from_attachment(
                _SourceDocumentProjection(
                    source=source,
                    upload=upload,
                    episode_id=episode.id,
                    now=now,
                    uuid_factory=request.uuid_factory,
                )
            )
        )
    return episode


async def persist_draft_script(
    uow: CanonicalUnitOfWork,
    request: DraftScriptPersistenceRequest,
) -> CanonicalEpisode:
    """Persist generated TEI and no-QA provenance onto an episode."""
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
        msg = f"Upload {source.upload_id} was not found for ingestion source."
        raise DraftScriptPersistenceError(msg)
    return upload


def _source_document_from_attachment(
    projection: _SourceDocumentProjection,
) -> SourceDocument:
    """Project an intake source attachment into canonical source metadata."""
    return SourceDocument(
        id=projection.uuid_factory(),
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
    metadata_hash = source.metadata.get("content_hash")
    if isinstance(metadata_hash, str) and metadata_hash.strip():
        return metadata_hash
    if upload is not None and upload.content_hash:
        return upload.content_hash
    return _sha256_text(f"{source.source_type}:{_source_uri(source, upload)}")


def _validate_draft_result(result: DraftScriptResult) -> None:
    """Validate draft result metadata before writing episode TEI."""
    expected_hash = _sha256_text(result.tei_xml)
    if result.content_hash != expected_hash:
        msg = "Draft script content_hash does not match tei_xml."
        raise DraftScriptPersistenceError(msg)


def _sha256_text(value: str) -> str:
    """Return a prefixed SHA-256 text hash."""
    return f"sha256:{hashlib.sha256(value.encode()).hexdigest()}"
