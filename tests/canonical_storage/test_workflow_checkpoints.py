"""SQLAlchemy checkpoint adapter tests."""

import asyncio
import typing as typ
import uuid

import pytest
import sqlalchemy as sa

from episodic.canonical.storage import SqlAlchemyUnitOfWork, WorkflowCheckpointRecord
from episodic.orchestration import WorkflowCheckpoint

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def _checkpoint(*, checkpoint_id: str | None = None) -> WorkflowCheckpoint:
    """Return a deterministic checkpoint fixture."""
    return WorkflowCheckpoint(
        checkpoint_id=checkpoint_id or str(uuid.uuid4()),
        workflow_id="corr-storage",
        workflow_type="generation_orchestration",
        step_name="execute",
        idempotency_key="corr-storage:generation_orchestration:execute:action-1:0",
        payload={
            "request": {"correlation_id": "corr-storage"},
            "planner_result": {"plan": {"steps": []}},
        },
    )


@pytest.mark.asyncio
async def test_checkpoint_store_persists_across_unit_of_work(
    session_factory: object,
) -> None:
    """Checkpoint records should survive fresh unit-of-work instances."""
    factory = typ.cast("async_sessionmaker[AsyncSession]", session_factory)
    checkpoint = _checkpoint()

    async with SqlAlchemyUnitOfWork(factory) as uow:
        stored = await uow.workflow_checkpoints.save_or_reuse(checkpoint)
        await uow.commit()

    async with SqlAlchemyUnitOfWork(factory) as uow:
        fetched = await uow.workflow_checkpoints.get(stored.checkpoint_id)

    assert fetched is not None
    assert fetched.idempotency_key == checkpoint.idempotency_key
    assert fetched.payload["request"] == {"correlation_id": "corr-storage"}


@pytest.mark.asyncio
async def test_checkpoint_store_get_returns_none_for_missing_checkpoint(
    session_factory: object,
) -> None:
    """`get` should return None when the checkpoint does not exist."""
    factory = typ.cast("async_sessionmaker[AsyncSession]", session_factory)

    async with SqlAlchemyUnitOfWork(factory) as uow:
        result = await uow.workflow_checkpoints.get(str(uuid.uuid4()))

    assert result is None


@pytest.mark.asyncio
async def test_checkpoint_store_get_by_idempotency_key_returns_none_for_missing_key(
    session_factory: object,
) -> None:
    """`get_by_idempotency_key` should return None for unknown keys."""
    factory = typ.cast("async_sessionmaker[AsyncSession]", session_factory)

    async with SqlAlchemyUnitOfWork(factory) as uow:
        result = await uow.workflow_checkpoints.get_by_idempotency_key(
            "non-existent-idempotency-key"
        )

    assert result is None


@pytest.mark.asyncio
async def test_checkpoint_store_reuses_idempotency_key(
    session_factory: object,
) -> None:
    """Saving the same step key twice should return the first checkpoint."""
    factory = typ.cast("async_sessionmaker[AsyncSession]", session_factory)
    checkpoint = _checkpoint()
    duplicate = _checkpoint(checkpoint_id=str(uuid.uuid4()))

    async with SqlAlchemyUnitOfWork(factory) as uow:
        first = await uow.workflow_checkpoints.save_or_reuse(checkpoint)
        second = await uow.workflow_checkpoints.save_or_reuse(duplicate)
        await uow.commit()

    assert second.checkpoint_id == first.checkpoint_id


@pytest.mark.asyncio
async def test_checkpoint_store_reuses_concurrent_idempotency_key(
    session_factory: object,
) -> None:
    """Concurrent saves with one step key should persist one checkpoint."""
    factory = typ.cast("async_sessionmaker[AsyncSession]", session_factory)
    key = "corr-storage:generation_orchestration:execute:action-2:0"
    first = WorkflowCheckpoint(
        checkpoint_id=str(uuid.uuid4()),
        workflow_id="corr-storage",
        workflow_type="generation_orchestration",
        step_name="execute",
        idempotency_key=key,
        payload={"planner_result": {}},
    )
    duplicate = WorkflowCheckpoint(
        checkpoint_id=str(uuid.uuid4()),
        workflow_id="corr-storage",
        workflow_type="generation_orchestration",
        step_name="execute",
        idempotency_key=key,
        payload={"planner_result": {}},
    )

    async def save_checkpoint(
        checkpoint: WorkflowCheckpoint,
    ) -> WorkflowCheckpoint:
        async with SqlAlchemyUnitOfWork(factory) as uow:
            stored = await uow.workflow_checkpoints.save_or_reuse(checkpoint)
            await uow.commit()
            return stored

    stored_first, stored_second = await asyncio.gather(
        save_checkpoint(first),
        save_checkpoint(duplicate),
    )

    async with SqlAlchemyUnitOfWork(factory) as uow:
        persisted = await uow.workflow_checkpoints.get_by_idempotency_key(key)

    async with factory() as session:
        persisted_count = await session.scalar(
            sa
            .select(sa.func.count())
            .select_from(WorkflowCheckpointRecord)
            .where(WorkflowCheckpointRecord.idempotency_key == key)
        )

    assert stored_second.checkpoint_id == stored_first.checkpoint_id
    assert persisted is not None
    assert persisted.checkpoint_id == stored_first.checkpoint_id
    assert persisted_count == 1


@pytest.mark.asyncio
async def test_checkpoint_store_marks_checkpoint_resumed(
    session_factory: object,
) -> None:
    """`mark_resumed` should persist the resumed checkpoint status."""
    factory = typ.cast("async_sessionmaker[AsyncSession]", session_factory)
    checkpoint = _checkpoint()

    async with SqlAlchemyUnitOfWork(factory) as uow:
        stored = await uow.workflow_checkpoints.save_or_reuse(checkpoint)
        resumed = await uow.workflow_checkpoints.mark_resumed(stored.checkpoint_id)
        await uow.commit()

    async with SqlAlchemyUnitOfWork(factory) as uow:
        fetched = await uow.workflow_checkpoints.get(stored.checkpoint_id)

    assert resumed.status == "resumed"
    assert fetched is not None
    assert fetched.status == "resumed"


@pytest.mark.asyncio
async def test_checkpoint_store_mark_resumed_rollback_leaves_suspended(
    session_factory: object,
) -> None:
    """Rolled-back resume markers should leave checkpoints retryable."""
    factory = typ.cast("async_sessionmaker[AsyncSession]", session_factory)
    checkpoint = _checkpoint()

    async with SqlAlchemyUnitOfWork(factory) as uow:
        stored = await uow.workflow_checkpoints.save_or_reuse(checkpoint)
        await uow.commit()

    async with SqlAlchemyUnitOfWork(factory) as uow:
        resumed = await uow.workflow_checkpoints.mark_resumed(stored.checkpoint_id)
        await uow.rollback()

    async with SqlAlchemyUnitOfWork(factory) as uow:
        fetched = await uow.workflow_checkpoints.get(stored.checkpoint_id)

    assert resumed.status == "resumed"
    assert fetched is not None
    assert fetched.status == "suspended"


@pytest.mark.asyncio
async def test_checkpoint_store_mark_resumed_raises_for_unknown_checkpoint_id(
    session_factory: object,
) -> None:
    """`mark_resumed` on an unknown id must raise ValueError."""
    factory = typ.cast("async_sessionmaker[AsyncSession]", session_factory)

    async with SqlAlchemyUnitOfWork(factory) as uow:
        with pytest.raises(ValueError, match="unknown checkpoint"):
            await uow.workflow_checkpoints.mark_resumed(str(uuid.uuid4()))
