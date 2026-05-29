"""Checkpoint adapter persistence and transaction contract tests.

These tests exercise `SqlAlchemyWorkflowCheckpointStore` through
`SqlAlchemyUnitOfWork.workflow_checkpoints`. They cover idempotent checkpoint
creation, concurrent save convergence, resume commit and rollback semantics,
and the atomicity guarantees expected by orchestration suspend/resume paths.
"""

import asyncio
import typing as typ
import uuid
from unittest import mock

import hypothesis.strategies as st
import pytest
import sqlalchemy as sa
from hypothesis import HealthCheck, given, settings
from sqlalchemy.exc import IntegrityError

from episodic.canonical.storage import (
    SqlAlchemyUnitOfWork,
    SqlAlchemyWorkflowCheckpointStore,
    WorkflowCheckpointRecord,
)
from tests.canonical_storage._workflow_checkpoint_support import (
    RecordingMetrics,
    StepClock,
    make_checkpoint,
)

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
    from syrupy.assertion import SnapshotAssertion

    from episodic.orchestration import WorkflowCheckpoint


_short_delays = st.sampled_from((0.0, 0.001, 0.005))


@pytest.mark.asyncio
async def test_checkpoint_store_persists_across_unit_of_work(
    session_factory: object,
) -> None:
    """Checkpoint records should survive fresh unit-of-work instances."""
    factory = typ.cast("async_sessionmaker[AsyncSession]", session_factory)
    checkpoint = make_checkpoint()

    async with SqlAlchemyUnitOfWork(factory) as uow:
        stored = await uow.workflow_checkpoints.save_or_reuse(checkpoint)
        await uow.commit()

    async with SqlAlchemyUnitOfWork(factory) as uow:
        fetched = await uow.workflow_checkpoints.get(stored.checkpoint_id)

    assert fetched is not None
    assert fetched.idempotency_key == checkpoint.idempotency_key
    assert fetched.payload["request"] == {"correlation_id": "corr-storage"}


@pytest.mark.asyncio
async def test_checkpoint_store_get_returns_none_for_missingmake_checkpoint(
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
    checkpoint = make_checkpoint()
    duplicate = make_checkpoint(checkpoint_id=str(uuid.uuid4()))

    async with SqlAlchemyUnitOfWork(factory) as uow:
        first = await uow.workflow_checkpoints.save_or_reuse(checkpoint)
        second = await uow.workflow_checkpoints.save_or_reuse(duplicate)
        await uow.commit()

    assert second.checkpoint_id == first.checkpoint_id


@pytest.mark.asyncio
async def test_checkpoint_store_records_checkpoint_metrics(
    session_factory: object,
    snapshot: SnapshotAssertion,
) -> None:
    """Checkpoint operations should record bounded outcome and latency metrics."""
    factory = typ.cast("async_sessionmaker[AsyncSession]", session_factory)
    metrics = RecordingMetrics()
    key = "corr-storage:generation_orchestration:execute:metrics:0"
    checkpoint = make_checkpoint(idempotency_key=key)
    duplicate = make_checkpoint(checkpoint_id=str(uuid.uuid4()), idempotency_key=key)

    async with factory() as session:
        store = SqlAlchemyWorkflowCheckpointStore(
            session,
            metrics=metrics,
            clock=StepClock(),
        )
        first = await store.save_or_reuse(checkpoint)
        second = await store.save_or_reuse(duplicate)
        await session.commit()

    async with SqlAlchemyUnitOfWork(factory) as uow:
        stored = await uow.workflow_checkpoints.save_or_reuse(make_checkpoint())
        await uow.commit()

    async with factory() as session:
        store = SqlAlchemyWorkflowCheckpointStore(
            session,
            metrics=metrics,
            clock=StepClock(),
        )
        await store.mark_resumed(stored.checkpoint_id)
        with pytest.raises(ValueError, match="unknown checkpoint"):
            await store.mark_resumed(str(uuid.uuid4()))
        await session.rollback()

    assert second.checkpoint_id == first.checkpoint_id
    assert metrics.as_snapshot() == snapshot


@pytest.mark.asyncio
async def test_checkpoint_store_records_recovery_failure_metrics(
    snapshot: SnapshotAssertion,
) -> None:
    """Persisted conflict without a recoverable checkpoint records failure metrics."""
    metrics = RecordingMetrics()
    clock = StepClock()
    checkpoint = make_checkpoint(
        idempotency_key="corr-storage:generation_orchestration:execute:race:0"
    )

    # Construct an IntegrityError that mirrors what SQLAlchemy raises when the
    # database rejects a duplicate idempotency key.
    integrity_error = IntegrityError(
        statement="INSERT INTO workflow_checkpoints ...",
        params={},
        orig=Exception("UNIQUE constraint failed: idempotency_key"),
    )

    # The `begin_nested()` call returns an async context manager. The session
    # `flush()` inside that context manager raises IntegrityError so the savepoint
    # rolls back and the error propagates to the adapter's except branch.
    savepoint_cm = mock.MagicMock()
    savepoint_cm.__aenter__ = mock.AsyncMock(return_value=savepoint_cm)
    savepoint_cm.__aexit__ = mock.AsyncMock(return_value=None)

    # `execute()` is awaited and must return an object whose `scalar_one_or_none()`
    # returns `None`, simulating the conflicting row vanishing before recovery.
    empty_result = mock.MagicMock()
    empty_result.scalar_one_or_none.return_value = None

    session = mock.MagicMock()
    session.begin_nested = mock.MagicMock(return_value=savepoint_cm)
    session.add = mock.MagicMock()
    session.flush = mock.AsyncMock(side_effect=integrity_error)
    session.execute = mock.AsyncMock(return_value=empty_result)

    store = SqlAlchemyWorkflowCheckpointStore(
        typ.cast("AsyncSession", session),
        metrics=metrics,
        clock=clock,
    )

    with pytest.raises(IntegrityError):
        await store.save_or_reuse(checkpoint)

    assert metrics.as_snapshot() == snapshot


@pytest.mark.asyncio
async def test_checkpoint_store_reuses_concurrent_idempotency_key(
    session_factory: object,
) -> None:
    """Concurrent saves with one step key should persist one checkpoint."""
    factory = typ.cast("async_sessionmaker[AsyncSession]", session_factory)
    key = "corr-storage:generation_orchestration:execute:action-2:0"
    first = make_checkpoint(checkpoint_id=str(uuid.uuid4()), idempotency_key=key)
    duplicate = make_checkpoint(checkpoint_id=str(uuid.uuid4()), idempotency_key=key)

    async def save_checkpoint(checkpoint: WorkflowCheckpoint) -> WorkflowCheckpoint:
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
@pytest.mark.parametrize(
    ("resume_mode", "expected_fetched_status"),
    [
        ("commit", "resumed"),
        ("rollback", "suspended"),
    ],
    ids=["commit", "rollback"],
)
async def test_checkpoint_store_mark_resumed_status(
    session_factory: object,
    resume_mode: str,
    expected_fetched_status: str,
) -> None:
    """mark_resumed persists status on commit and leaves it suspended on rollback."""
    factory = typ.cast("async_sessionmaker[AsyncSession]", session_factory)
    commit_resume = resume_mode == "commit"
    checkpoint = make_checkpoint()

    async with SqlAlchemyUnitOfWork(factory) as uow:
        stored = await uow.workflow_checkpoints.save_or_reuse(checkpoint)
        await uow.commit()

    async with SqlAlchemyUnitOfWork(factory) as uow:
        resumed = await uow.workflow_checkpoints.mark_resumed(stored.checkpoint_id)
        if commit_resume:
            await uow.commit()
        else:
            await uow.rollback()

    async with SqlAlchemyUnitOfWork(factory) as uow:
        fetched = await uow.workflow_checkpoints.get(stored.checkpoint_id)

    assert resumed.status == "resumed"
    assert fetched is not None
    assert fetched.status == expected_fetched_status


@pytest.mark.asyncio
@given(
    first_delay=_short_delays,
    second_delay=_short_delays,
)
@settings(
    deadline=None,
    max_examples=10,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
async def test_checkpoint_store_concurrent_idempotency_property(
    session_factory: object,
    first_delay: float,
    second_delay: float,
) -> None:
    """Property: racing saves for one idempotency key persist one checkpoint."""
    factory = typ.cast("async_sessionmaker[AsyncSession]", session_factory)
    key = f"prop:{uuid.uuid4()}:concurrent"
    first = make_checkpoint(checkpoint_id=str(uuid.uuid4()), idempotency_key=key)
    duplicate = make_checkpoint(checkpoint_id=str(uuid.uuid4()), idempotency_key=key)

    async def save_checkpoint(
        checkpoint: WorkflowCheckpoint,
        delay: float,
    ) -> WorkflowCheckpoint:
        await asyncio.sleep(delay)
        async with SqlAlchemyUnitOfWork(factory) as uow:
            stored = await uow.workflow_checkpoints.save_or_reuse(checkpoint)
            await uow.commit()
            return stored

    stored_first, stored_second = await asyncio.gather(
        save_checkpoint(first, first_delay),
        save_checkpoint(duplicate, second_delay),
    )

    async with factory() as session:
        persisted_count = await session.scalar(
            sa
            .select(sa.func.count())
            .select_from(WorkflowCheckpointRecord)
            .where(WorkflowCheckpointRecord.idempotency_key == key)
        )

    assert stored_second.checkpoint_id == stored_first.checkpoint_id
    assert persisted_count == 1


@pytest.mark.asyncio
@given(
    resume_mode=st.sampled_from(("commit", "rollback")),
)
@settings(
    deadline=None,
    max_examples=10,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
async def test_checkpoint_store_resume_atomicity_property(
    session_factory: object,
    resume_mode: str,
) -> None:
    """Property: rollback leaves a resume marker retryable; commit persists it."""
    factory = typ.cast("async_sessionmaker[AsyncSession]", session_factory)
    checkpoint = make_checkpoint(idempotency_key=f"prop:{uuid.uuid4()}:resume")
    expected_status = "resumed" if resume_mode == "commit" else "suspended"

    async with SqlAlchemyUnitOfWork(factory) as uow:
        stored = await uow.workflow_checkpoints.save_or_reuse(checkpoint)
        await uow.commit()

    async with SqlAlchemyUnitOfWork(factory) as uow:
        resumed = await uow.workflow_checkpoints.mark_resumed(stored.checkpoint_id)
        if resume_mode == "commit":
            await uow.commit()
        else:
            await uow.rollback()

    async with SqlAlchemyUnitOfWork(factory) as uow:
        fetched = await uow.workflow_checkpoints.get(stored.checkpoint_id)

    assert resumed.status == "resumed"
    assert fetched is not None
    assert fetched.status == expected_status


@pytest.mark.asyncio
async def test_checkpoint_store_mark_resumed_raises_for_unknown_checkpoint_id(
    session_factory: object,
) -> None:
    """`mark_resumed` on an unknown id must raise ValueError."""
    factory = typ.cast("async_sessionmaker[AsyncSession]", session_factory)

    async with SqlAlchemyUnitOfWork(factory) as uow:
        with pytest.raises(ValueError, match="unknown checkpoint"):
            await uow.workflow_checkpoints.mark_resumed(str(uuid.uuid4()))
