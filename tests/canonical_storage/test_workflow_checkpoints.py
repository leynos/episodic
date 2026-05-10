"""SQLAlchemy checkpoint adapter tests."""

from __future__ import annotations

import typing as typ
import uuid

import pytest

from episodic.canonical.storage import SqlAlchemyUnitOfWork
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
        stored = await uow.workflow_checkpoints.save(checkpoint)
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
        first = await uow.workflow_checkpoints.save(checkpoint)
        second = await uow.workflow_checkpoints.save(duplicate)
        await uow.commit()

    assert second.checkpoint_id == first.checkpoint_id


@pytest.mark.asyncio
async def test_checkpoint_store_marks_checkpoint_resumed(
    session_factory: object,
) -> None:
    """`mark_resumed` should persist the resumed checkpoint status."""
    factory = typ.cast("async_sessionmaker[AsyncSession]", session_factory)
    checkpoint = _checkpoint()

    async with SqlAlchemyUnitOfWork(factory) as uow:
        stored = await uow.workflow_checkpoints.save(checkpoint)
        resumed = await uow.workflow_checkpoints.mark_resumed(stored.checkpoint_id)
        await uow.commit()

    async with SqlAlchemyUnitOfWork(factory) as uow:
        fetched = await uow.workflow_checkpoints.get(stored.checkpoint_id)

    assert resumed.status == "resumed"
    assert fetched is not None
    assert fetched.status == "resumed"
