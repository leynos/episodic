"""QA artefact reads must not write, or discard, the caller's staged work.

``AsyncSession`` autoflushes before a query emits SQL, and ``populate_existing``
overwrites an identity-mapped record with the stored row. Either turns a
question into a write, so both boundaries are pinned here for the artefact
store.
"""

import datetime as dt
import typing as typ
import uuid

import pytest
import sqlalchemy as sa

from episodic.canonical.pagination import Pagination
from episodic.canonical.qa_artefact_ports import QaEvaluationListRequest
from episodic.canonical.storage import (
    QaEvaluationRecord,
    SqlAlchemyQaArtefactStore,
    SqlAlchemyUnitOfWork,
)
from episodic.canonical.storage.qa_artefact_mappers import evaluation_to_record
from tests.canonical_storage._qa_artefact_support import (
    create_episode,
    make_evaluation,
)

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

NOW = dt.datetime(2026, 10, 31, 9, 0, tzinfo=dt.UTC)


@pytest.mark.asyncio
async def test_reads_do_not_flush_the_callers_pending_work(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A QA read must not turn into a write through autoflush.

    A caller can hold staged changes while it reads. Autoflush would send
    them, so a pending constraint failure would surface from a query that
    never wrote, and the query would see uncommitted state.
    """
    episode_id = await create_episode(session_factory)
    pending = evaluation_to_record(
        make_evaluation(episode_id, idempotency_key="pending"),
        created_at=NOW,
    )

    async with session_factory() as session:
        session.add(pending)
        store = SqlAlchemyQaArtefactStore(session)

        assert await store.get_evaluation(uuid.uuid7()) is None, (
            "an unknown evaluation should read as absent"
        )
        assert pending in session.new, "get_evaluation flushed the pending record"

        await store.list_evaluations(
            QaEvaluationListRequest(
                episode_id=episode_id,
                pagination=Pagination(limit=10, offset=0),
            )
        )
        assert pending in session.new, "list_evaluations flushed the pending record"

        await session.rollback()
        assert await session.scalar(sa.text("SELECT 1")) == 1, (
            "the session should remain usable after the reads"
        )


@pytest.mark.asyncio
async def test_get_evaluation_keeps_staged_edits_to_a_loaded_record(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """An ordinary read must not refresh, and so discard, staged edits.

    ``populate_existing`` overwrites an identity-mapped record with the stored
    row. Only the write paths, which have just flushed their own changes, may
    ask for that; a plain read must leave the caller's unflushed edits alone.
    """
    episode_id = await create_episode(session_factory)
    evaluation = make_evaluation(episode_id, idempotency_key="staged-edit")
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        stored = await uow.qa_artefacts.record_evaluation(evaluation)
        await uow.commit()

    async with session_factory() as session:
        record = await session.get(QaEvaluationRecord, stored.summary_record.id)
        assert record is not None, "the recorded evaluation should be readable"
        record.summary = "staged but unflushed"

        fetched = await SqlAlchemyQaArtefactStore(session).get_evaluation(
            stored.summary_record.id
        )

        assert fetched is not None, "the stored evaluation should read back"
        assert record.summary == "staged but unflushed", (
            "get_evaluation refreshed the record and discarded the staged edit"
        )
