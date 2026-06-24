"""Tests for draft-generation persistence services."""

import datetime as dt
import hashlib
import typing as typ
import uuid

import pytest

from episodic.canonical.domain import (
    GenerationRun,
    GenerationRunStatus,
    IngestionJob,
    IngestionStatus,
    IntakeState,
    SeriesProfile,
)
from episodic.canonical.generation_persistence import (
    DraftScriptPersistenceError,
    DraftScriptPersistenceRequest,
    EpisodeMaterialisationRequest,
    InvalidDraftTeiError,
    materialise_episode_from_ingestion,
    persist_draft_script,
)
from episodic.canonical.generation_quality import QaStatus, QualityMode
from episodic.canonical.ingestion_sources import AttachmentKind, IngestionJobSource
from episodic.canonical.storage import SqlAlchemyUnitOfWork
from episodic.generation.draft_script import DraftScriptResult
from episodic.llm import LLMUsage

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


NOW = dt.datetime(2026, 6, 24, 12, 0, tzinfo=dt.UTC)


class SequentialUuids:
    """Deterministic UUID factory for persistence service tests."""

    def __init__(self) -> None:
        self.values = iter([
            uuid.UUID("00000000-0000-0000-0000-000000000101"),
            uuid.UUID("00000000-0000-0000-0000-000000000102"),
            uuid.UUID("00000000-0000-0000-0000-000000000103"),
            uuid.UUID("00000000-0000-0000-0000-000000000104"),
        ])

    def __call__(self) -> uuid.UUID:
        """Return the next deterministic UUID."""
        return next(self.values)


def _clock() -> dt.datetime:
    """Return the frozen persistence timestamp."""
    return NOW


def _series_profile() -> SeriesProfile:
    """Return a series profile fixture."""
    return SeriesProfile(
        id=uuid.UUID("00000000-0000-0000-0000-000000000201"),
        slug="bridgewater",
        title="Bridgewater",
        description=None,
        configuration={},
        guardrails={},
        created_at=NOW,
        updated_at=NOW,
    )


def _ingestion_job(
    series_profile_id: uuid.UUID,
    episode_id: uuid.UUID | None,
) -> IngestionJob:
    """Return an intake job ready for generation."""
    return IngestionJob(
        id=uuid.UUID("00000000-0000-0000-0000-000000000301"),
        series_profile_id=series_profile_id,
        target_episode_id=episode_id,
        status=IngestionStatus.PENDING,
        requested_at=NOW,
        started_at=None,
        completed_at=None,
        error_message=None,
        created_at=NOW,
        updated_at=NOW,
        intake_state=IntakeState.READY_FOR_GENERATION,
    )


def _source(job_id: uuid.UUID) -> IngestionJobSource:
    """Return one attached source for a ready ingestion job."""
    return IngestionJobSource(
        id=uuid.UUID("00000000-0000-0000-0000-000000000401"),
        ingestion_job_id=job_id,
        attachment_kind=AttachmentKind.SOURCE_URI,
        upload_id=None,
        source_uri="https://example.test/source.md",
        source_type="research_brief",
        weight=1.0,
        metadata={"content_hash": "sha256:source"},
        created_at=NOW,
    )


def _run(episode_id: uuid.UUID, source_bundle_id: uuid.UUID) -> GenerationRun:
    """Return a pending no-QA generation run for persistence tests."""
    return GenerationRun(
        id=uuid.UUID("00000000-0000-0000-0000-000000000501"),
        episode_id=episode_id,
        source_bundle_id=source_bundle_id,
        actor="editor@example.test",
        status=GenerationRunStatus.RUNNING,
        current_node="draft",
        budget_snapshot={},
        configuration={},
        created_at=NOW,
        updated_at=NOW,
        started_at=NOW,
        ended_at=None,
        error_message=None,
        quality_mode=QualityMode.DRAFT_WITHOUT_QA,
        qa_status=QaStatus.SKIPPED,
        skip_qa_rationale="Vertical slice test.",
    )


def _draft_result(tei_xml: str) -> DraftScriptResult:
    """Return a draft script result for persistence tests."""
    return DraftScriptResult(
        tei_xml=tei_xml,
        content_hash=f"sha256:{hashlib.sha256(tei_xml.encode()).hexdigest()}",
        usage=LLMUsage(input_tokens=10, output_tokens=20, total_tokens=30),
        model="vidai-mock",
        provider_response_id="resp-1",
        finish_reason="stop",
    )


async def _persist_ready_job(
    factory: async_sessionmaker[AsyncSession],
) -> tuple[SeriesProfile, IngestionJob]:
    """Persist a ready intake job with one source attachment."""
    series = _series_profile()
    job = _ingestion_job(series.id, None)
    async with SqlAlchemyUnitOfWork(factory) as uow:
        await uow.series_profiles.add(series)
        await uow.flush()
        await uow.ingestion_jobs.add(job)
        await uow.ingestion_job_sources.add(_source(job.id))
        await uow.commit()
    return series, job


@pytest.mark.asyncio
async def test_materialise_episode_from_ingestion_creates_placeholder_episode(
    session_factory: object,
) -> None:
    """A ready ingestion job should materialise an episode and source rows."""
    factory = typ.cast("async_sessionmaker[AsyncSession]", session_factory)
    episode_id = uuid.UUID("00000000-0000-0000-0000-000000000101")
    _, job = await _persist_ready_job(factory)

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
        await uow.commit()

    assert episode.id == episode_id
    assert episode.title == "Bridgewater Futures"
    assert episode.tei_revision == 1
    assert "Draft generation pending." in episode.tei_xml

    async with SqlAlchemyUnitOfWork(factory) as uow:
        fetched = await uow.episodes.get(episode_id)
        documents = await uow.source_documents.list_for_job(job.id)

    assert fetched is not None
    assert fetched.tei_header_id == episode.tei_header_id
    assert [document.canonical_episode_id for document in documents] == [episode_id]
    assert documents[0].content_hash == "sha256:source"


@pytest.mark.asyncio
async def test_persist_draft_script_records_no_qa_revision_metadata(
    session_factory: object,
) -> None:
    """Persisting a generated draft should update TEI and provenance fields."""
    factory = typ.cast("async_sessionmaker[AsyncSession]", session_factory)
    _, job = await _persist_ready_job(factory)
    draft_xml = (
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
        updated = await persist_draft_script(
            uow,
            DraftScriptPersistenceRequest(
                episode_id=episode.id,
                generation_run_id=run.id,
                result=_draft_result(draft_xml),
                expected_revision=episode.tei_revision,
                clock=_clock,
            ),
        )
        await uow.commit()

    assert updated.tei_xml == draft_xml
    assert updated.tei_revision == 2
    assert updated.tei_content_hash == _draft_result(draft_xml).content_hash
    assert updated.qa_status is QaStatus.SKIPPED
    assert updated.last_generation_run_id == run.id
    assert updated.updated_at == NOW


@pytest.mark.asyncio
async def test_persist_draft_script_rejects_invalid_tei(
    session_factory: object,
) -> None:
    """Invalid generated TEI should become a typed persistence failure."""
    factory = typ.cast("async_sessionmaker[AsyncSession]", session_factory)
    _, job = await _persist_ready_job(factory)

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
        with pytest.raises(InvalidDraftTeiError):
            await persist_draft_script(
                uow,
                DraftScriptPersistenceRequest(
                    episode_id=episode.id,
                    generation_run_id=run.id,
                    result=_draft_result("<TEI>broken"),
                    expected_revision=episode.tei_revision,
                    clock=_clock,
                ),
            )


@pytest.mark.asyncio
async def test_materialise_episode_requires_attached_sources(
    session_factory: object,
) -> None:
    """Materialisation should fail loudly when an intake job has no sources."""
    factory = typ.cast("async_sessionmaker[AsyncSession]", session_factory)
    series = _series_profile()
    job = _ingestion_job(series.id, None)
    async with SqlAlchemyUnitOfWork(factory) as uow:
        await uow.series_profiles.add(series)
        await uow.flush()
        await uow.ingestion_jobs.add(job)
        await uow.commit()

    async with SqlAlchemyUnitOfWork(factory) as uow:
        with pytest.raises(DraftScriptPersistenceError, match="sources"):
            await materialise_episode_from_ingestion(
                uow,
                EpisodeMaterialisationRequest(
                    ingestion_job_id=job.id,
                    title="Bridgewater Futures",
                    clock=_clock,
                    uuid_factory=SequentialUuids(),
                ),
            )
