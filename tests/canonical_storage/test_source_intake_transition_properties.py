"""Property tests for source-intake storage transitions."""

from __future__ import annotations

import asyncio
import datetime as dt
import typing as typ
import uuid

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from episodic.canonical.domain import (
    IngestionJob,
    IngestionStatus,
    IntakeState,
    SeriesProfile,
)
from episodic.canonical.storage import SqlAlchemyUnitOfWork

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@pytest.mark.asyncio
@pytest.mark.hypothesis
@given(
    delays=st.lists(
        st.floats(min_value=0.0, max_value=0.005, allow_nan=False),
        min_size=2,
        max_size=5,
    )
)
@settings(
    deadline=None,
    max_examples=10,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
async def test_ingestion_job_transition_is_concurrently_at_most_once_property(
    session_factory: object,
    delays: list[float],
) -> None:
    """Property: concurrent intake-state transitions succeed at most once."""
    factory = typ.cast("async_sessionmaker[AsyncSession]", session_factory)
    series = _make_series_profile()
    job = _make_ingestion_job(series.id)
    async with SqlAlchemyUnitOfWork(factory) as uow:
        await uow.series_profiles.add(series)
        await uow.flush()
        await uow.ingestion_jobs.add(job)
        await uow.commit()

    results = await asyncio.gather(
        *(_transition(factory, job.id, delay) for delay in delays)
    )

    async with SqlAlchemyUnitOfWork(factory) as uow:
        fetched = await uow.ingestion_jobs.get(job.id)

    assert sum(results) == 1
    assert fetched is not None
    assert fetched.intake_state is IntakeState.READY_FOR_GENERATION


async def _transition(
    factory: async_sessionmaker[AsyncSession],
    job_id: uuid.UUID,
    delay: float,
) -> bool:
    """Attempt one conditional intake-state transition after a delay."""
    await asyncio.sleep(delay)
    async with SqlAlchemyUnitOfWork(factory) as uow:
        transitioned = await uow.ingestion_jobs.transition_intake_state(
            job_id,
            from_state=IntakeState.AWAITING_SOURCES,
            to_state=IntakeState.READY_FOR_GENERATION,
        )
        await uow.commit()
        return transitioned


def _make_series_profile() -> SeriesProfile:
    """Return one series-profile fixture for source-intake storage tests."""
    now = dt.datetime.now(dt.UTC)
    profile_id = uuid.uuid4()
    return SeriesProfile(
        id=profile_id,
        slug=f"transition-{profile_id}",
        title="Transition Property",
        description="Profile for transition property tests.",
        configuration={"tone": "clear"},
        guardrails={},
        created_at=now,
        updated_at=now,
    )


def _make_ingestion_job(series_profile_id: uuid.UUID) -> IngestionJob:
    """Return one awaiting-sources ingestion job fixture."""
    now = dt.datetime.now(dt.UTC)
    return IngestionJob(
        id=uuid.uuid4(),
        series_profile_id=series_profile_id,
        target_episode_id=None,
        status=IngestionStatus.PENDING,
        requested_at=now,
        started_at=None,
        completed_at=None,
        error_message=None,
        created_at=now,
        updated_at=now,
        intake_state=IntakeState.AWAITING_SOURCES,
    )
