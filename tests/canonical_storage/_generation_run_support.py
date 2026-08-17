"""Shared generation-run SQL storage test support."""

import datetime as dt
import typing as typ
import uuid

import sqlalchemy as sa

from episodic.canonical.domain import (
    ApprovalState,
    CanonicalEpisode,
    EpisodeStatus,
    GenerationRun,
    GenerationRunStatus,
    IngestionJob,
    IngestionStatus,
    SeriesProfile,
    TeiHeader,
)
from episodic.canonical.generation_quality import QaStatus, QualityMode
from episodic.canonical.storage import SqlAlchemyUnitOfWork

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


NOW = dt.datetime(2026, 6, 24, 8, 30, tzinfo=dt.UTC)


def make_generation_run(
    *,
    run_id: uuid.UUID | None = None,
    episode_id: uuid.UUID | None = None,
    source_bundle_id: uuid.UUID | None = None,
    status: GenerationRunStatus = GenerationRunStatus.PENDING,
    created_at: dt.datetime = NOW,
) -> GenerationRun:
    """Build a no-QA generation run for storage tests."""
    return GenerationRun(
        id=run_id or uuid.uuid7(),
        episode_id=episode_id or uuid.uuid7(),
        source_bundle_id=source_bundle_id or uuid.uuid7(),
        actor="editor@example.com",
        status=status,
        current_node=None,
        budget_snapshot={"limit_usd": "5.00"},
        configuration={"quality_mode": QualityMode.DRAFT_WITHOUT_QA.value},
        created_at=created_at,
        updated_at=created_at,
        started_at=None,
        ended_at=None,
        error_message=None,
        quality_mode=QualityMode.DRAFT_WITHOUT_QA,
        qa_status=QaStatus.SKIPPED,
        skip_qa_rationale="No-QA vertical-slice draft.",
    )


async def persist_generation_run_prerequisites(
    session_factory: async_sessionmaker[AsyncSession],
    *runs: GenerationRun,
) -> None:
    """Persist the episode and source-bundle rows referenced by test runs."""
    series_id = uuid.uuid7()
    series = SeriesProfile(
        id=series_id,
        slug=f"generation-run-{series_id}",
        title="Generation run test series",
        description=None,
        configuration={},
        guardrails={},
        created_at=NOW,
        updated_at=NOW,
    )
    headers: dict[uuid.UUID, TeiHeader] = {}
    episodes: dict[uuid.UUID, CanonicalEpisode] = {}
    jobs: dict[uuid.UUID, IngestionJob] = {}

    for run in runs:
        if run.episode_id not in episodes:
            header = TeiHeader(
                id=uuid.uuid7(),
                title="Generation run test episode",
                payload={},
                raw_xml="<TEI/>",
                created_at=NOW,
                updated_at=NOW,
            )
            headers[run.episode_id] = header
            episodes[run.episode_id] = CanonicalEpisode(
                id=run.episode_id,
                series_profile_id=series.id,
                tei_header_id=header.id,
                title=header.title,
                tei_xml=header.raw_xml,
                status=EpisodeStatus.DRAFT,
                approval_state=ApprovalState.DRAFT,
                created_at=NOW,
                updated_at=NOW,
            )
        jobs.setdefault(
            run.source_bundle_id,
            IngestionJob(
                id=run.source_bundle_id,
                series_profile_id=series.id,
                target_episode_id=run.episode_id,
                status=IngestionStatus.COMPLETED,
                requested_at=NOW,
                started_at=NOW,
                completed_at=NOW,
                error_message=None,
                created_at=NOW,
                updated_at=NOW,
            ),
        )

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        await uow.series_profiles.add(series)
        for header in headers.values():
            await uow.tei_headers.add(header)
        await uow.commit()

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        for episode in episodes.values():
            await uow.episodes.add(episode)
        await uow.commit()

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        for job in jobs.values():
            await uow.ingestion_jobs.add(job)
        await uow.commit()


async def count_records(
    session_factory: async_sessionmaker[AsyncSession],
    record_type: type[object],
) -> int:
    """Count persisted records of one SQLAlchemy model type."""
    async with session_factory() as session:
        result = await session.execute(
            sa.select(sa.func.count()).select_from(record_type)
        )
        return result.scalar_one()


async def claim_run_in_independent_uow(
    session_factory: async_sessionmaker[AsyncSession],
    run_id: uuid.UUID,
    *,
    current_node: str | None,
    started_at: dt.datetime,
    lease_expires_at: dt.datetime | None,
) -> GenerationRun | None:
    """Claim a run within a separately committed unit of work."""
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        claimed = await uow.generation_runs.claim_run_for_execution(
            run_id,
            current_node=current_node,
            started_at=started_at,
            lease_expires_at=lease_expires_at,
        )
        await uow.commit()
        return claimed
