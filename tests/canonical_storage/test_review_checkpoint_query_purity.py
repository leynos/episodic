"""Read paths must not flush a caller's unrelated pending writes.

``AsyncSession.get`` and ``AsyncSession.execute`` autoflush by default: before
emitting SQL they flush whatever the session has staged. A read that only means
to answer a question therefore pushes a half-built object graph into the
transaction early, and any constraint violation in that graph surfaces at the
read rather than at the caller's own commit. The checkpoint store's query paths
open an explicit ``no_autoflush`` boundary so a caller can read while holding
unflushed work.
"""

import typing as typ
import uuid

import pytest

from episodic.canonical.domain import CheckpointStatus
from episodic.canonical.storage import (
    ReviewCheckpointRecord,
    SqlAlchemyReviewCheckpointStore,
    SqlAlchemyUnitOfWork,
)
from tests.canonical_storage import _generation_run_support as support

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def _pending_record(run_id: uuid.UUID) -> ReviewCheckpointRecord:
    """Build a valid checkpoint row that the caller has not flushed yet."""
    return ReviewCheckpointRecord(
        id=uuid.uuid7(),
        generation_run_id=run_id,
        node="review",
        prompt="Approve the draft?",
        options=["approve", "reject"],
        status=CheckpointStatus.CREATED,
        response_action=None,
        response_payload={},
        resolved_at=None,
        responded_by=None,
        created_at=support.NOW,
    )


async def _store_run(
    session_factory: async_sessionmaker[AsyncSession],
) -> uuid.UUID:
    """Commit one generation run whose foreign keys are satisfied."""
    run = support.make_generation_run()
    await support.persist_generation_run_prerequisites(session_factory, run)
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        await uow.generation_runs.create_run(run)
        await uow.commit()
    return run.id


@pytest.mark.asyncio
async def test_get_checkpoint_leaves_a_pending_write_unflushed(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """``get_checkpoint`` does not flush what the caller staged."""
    run_id = await _store_run(session_factory)
    async with session_factory() as session:
        staged = _pending_record(run_id)
        session.add(staged)
        assert staged in session.new, "test precondition: the row is pending"

        store = SqlAlchemyReviewCheckpointStore(session)
        assert await store.get_checkpoint(uuid.uuid7()) is None, (
            "test precondition: the identifier is unknown"
        )

        assert staged in session.new, "get_checkpoint flushed a pending write"
        await session.rollback()


@pytest.mark.asyncio
async def test_list_checkpoints_leaves_a_pending_write_unflushed(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """``list_checkpoints`` does not flush what the caller staged."""
    run_id = await _store_run(session_factory)
    async with session_factory() as session:
        staged = _pending_record(run_id)
        session.add(staged)
        assert staged in session.new, "test precondition: the row is pending"

        store = SqlAlchemyReviewCheckpointStore(session)
        listed = await store.list_checkpoints(run_id)

        assert staged in session.new, "list_checkpoints flushed a pending write"
        listed_ids = {checkpoint.id for checkpoint in listed}
        assert staged.id not in listed_ids, "the query saw an unflushed row"
        await session.rollback()
