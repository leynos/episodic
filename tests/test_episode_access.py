"""Regression tests for the shared episode ownership lookup.

Every episode-scoped resource runs :func:`read_owned_episode` before it exposes
data. These tests pin that the lookup stays a query path: a caller may hold
staged changes while it resolves ownership, and an autoflush there would turn
the check into a write.
"""

import datetime as dt
import typing as typ
import uuid

import pytest
import sqlalchemy as sa

from episodic.api.episode_access import read_owned_episode
from episodic.canonical.domain import (
    EpisodeTeiUpdate,
    GenerationRun,
    GenerationRunStatus,
)
from episodic.canonical.generation_quality import QaStatus
from episodic.canonical.storage import SqlAlchemyUnitOfWork
from episodic.canonical.storage.qa_artefact_mappers import evaluation_to_record
from tests.canonical_storage._qa_artefact_support import (
    create_episode,
    create_ingestion_job,
    make_evaluation,
)

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_ACTOR = "principal-a"


async def _episode_with_launcher_run(
    session_factory: async_sessionmaker[AsyncSession],
) -> uuid.UUID:
    """Persist an episode whose launcher run belongs to :data:`_ACTOR`."""
    episode_id = await create_episode(session_factory)
    source_bundle_id = await create_ingestion_job(session_factory, episode_id)
    now = dt.datetime.now(dt.UTC)
    run = GenerationRun(
        id=uuid.uuid7(),
        episode_id=episode_id,
        source_bundle_id=source_bundle_id,
        actor=_ACTOR,
        status=GenerationRunStatus.PENDING,
        current_node=None,
        budget_snapshot={},
        configuration={},
        created_at=now,
        updated_at=now,
        started_at=None,
        ended_at=None,
        error_message=None,
        qa_status=QaStatus.SKIPPED,
        skip_qa_rationale="Ownership test bypasses QA.",
    )
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        await uow.generation_runs.create_run(run)
        await uow.episodes.update(
            episode_id,
            update=EpisodeTeiUpdate(
                tei_xml="<TEI/>",
                qa_status=QaStatus.SKIPPED,
                last_generation_run_id=run.id,
                expected_revision=1,
                updated_at=now,
            ),
        )
        await uow.commit()
    return episode_id


@pytest.mark.asyncio
async def test_read_owned_episode_does_not_flush_staged_work(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Ownership reads leave the caller's pending rows unflushed.

    The staged evaluation names an episode that does not exist, so flushing it
    would violate the foreign key. An autoflush anywhere in the ownership
    lookup therefore fails the test loudly instead of only costing a write.
    Reaching the run read needs the episode row, so a failure there is what
    proves the boundary covers both queries rather than just the first.
    """
    episode_id = await _episode_with_launcher_run(session_factory)
    pending = evaluation_to_record(
        make_evaluation(uuid.uuid7(), idempotency_key="pending"),
        created_at=dt.datetime.now(dt.UTC),
    )

    session = session_factory()
    uow = SqlAlchemyUnitOfWork(lambda: session)
    async with uow:
        session.add(pending)

        episode = await read_owned_episode(uow, episode_id, _ACTOR)

        assert episode is not None, "the launcher's own episode was not resolved"
        assert pending in session.new, "read_owned_episode flushed staged work"
        assert await session.scalar(sa.text("SELECT 1")) == 1, (
            "the session stopped working after the ownership reads"
        )
