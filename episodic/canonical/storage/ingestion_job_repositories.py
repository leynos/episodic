"""SQLAlchemy repository for intake-aware ingestion jobs."""

from __future__ import annotations

import typing as typ

import sqlalchemy as sa

from episodic.canonical.entity_protocols import IngestionJobRepository

from .entity_mappers import _ingestion_job_from_record, _ingestion_job_to_record
from .entity_models import IngestionJobRecord
from .repository_base import _RepositoryBase

if typ.TYPE_CHECKING:
    import collections.abc as cabc
    import uuid

    from episodic.canonical.domain import (
        IngestionJob,
        IngestionJobListFilters,
        IntakeState,
    )


class SqlAlchemyIngestionJobRepository(_RepositoryBase, IngestionJobRepository):
    """Persist ingestion jobs and intake-state transitions with SQLAlchemy."""

    async def add(self, job: IngestionJob) -> None:
        """Add an ingestion job record."""
        await self._add_record(_ingestion_job_to_record(job))

    async def get(self, job_id: uuid.UUID) -> IngestionJob | None:
        """Fetch an ingestion job by identifier."""
        return await self._get_one_or_none(
            IngestionJobRecord,
            IngestionJobRecord.id == job_id,
            _ingestion_job_from_record,
        )

    async def get_for_update(self, job_id: uuid.UUID) -> IngestionJob | None:
        """Fetch and lock an ingestion job for transactional mutation."""
        result = await self._session.execute(
            sa
            .select(IngestionJobRecord)
            .where(IngestionJobRecord.id == job_id)
            .with_for_update()
        )
        record = result.scalar_one_or_none()
        return None if record is None else _ingestion_job_from_record(record)

    async def set_target_episode(
        self,
        job_id: uuid.UUID,
        *,
        episode_id: uuid.UUID,
    ) -> None:
        """Associate an ingestion job with its materialized episode."""
        await self._session.execute(
            sa
            .update(IngestionJobRecord)
            .where(IngestionJobRecord.id == job_id)
            .values(target_episode_id=episode_id, updated_at=sa.func.now())
        )

    async def list_paged(
        self,
        filters: IngestionJobListFilters,
        *,
        limit: int,
        offset: int,
    ) -> cabc.Sequence[IngestionJob]:
        """List ingestion jobs using source-intake filters."""
        statement = (
            sa
            .select(IngestionJobRecord)
            .where(_ingestion_job_filter_clause(filters))
            .order_by(IngestionJobRecord.created_at, IngestionJobRecord.id)
            .limit(limit)
            .offset(offset)
        )
        result = await self._session.execute(statement)
        return [_ingestion_job_from_record(row) for row in result.scalars()]

    async def count(self, filters: IngestionJobListFilters) -> int:
        """Count ingestion jobs using source-intake filters."""
        result = await self._session.execute(
            sa
            .select(sa.func.count())
            .select_from(IngestionJobRecord)
            .where(_ingestion_job_filter_clause(filters))
        )
        return result.scalar_one()

    async def transition_intake_state(
        self,
        job_id: uuid.UUID,
        *,
        from_state: IntakeState,
        to_state: IntakeState,
    ) -> bool:
        """Return True only when the conditional intake-state update matched."""
        statement = (
            sa
            .update(IngestionJobRecord)
            .where(
                sa.and_(
                    IngestionJobRecord.id == job_id,
                    IngestionJobRecord.intake_state == from_state,
                )
            )
            .values(intake_state=to_state, updated_at=sa.func.now())
        )
        result = typ.cast(
            "sa.CursorResult[typ.Any]",
            await self._session.execute(statement),
        )
        return result.rowcount == 1


def _ingestion_job_filter_clause(
    filters: IngestionJobListFilters,
) -> sa.ColumnElement[bool]:
    """Build the SQLAlchemy predicate for ingestion-job list filters."""
    clauses: list[sa.ColumnElement[bool]] = []
    if filters.series_profile_id is not None:
        clauses.append(
            IngestionJobRecord.series_profile_id == filters.series_profile_id
        )
    if filters.intake_state is not None:
        clauses.append(IngestionJobRecord.intake_state == filters.intake_state)
    return sa.and_(*clauses) if clauses else sa.true()
