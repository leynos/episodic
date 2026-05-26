"""Checkpoint adapter persistence and transaction contract tests.

These tests exercise `SqlAlchemyWorkflowCheckpointStore` through
`SqlAlchemyUnitOfWork.workflow_checkpoints`. They cover idempotent checkpoint
creation, concurrent save convergence, resume commit and rollback semantics,
and the atomicity guarantees expected by orchestration suspend/resume paths.
"""

import asyncio
import typing as typ
import uuid

import hypothesis.strategies as st
import pytest
import sqlalchemy as sa
from hypothesis import HealthCheck, given, settings

from episodic.canonical.storage import (
    SqlAlchemyUnitOfWork,
    SqlAlchemyWorkflowCheckpointStore,
    WorkflowCheckpointRecord,
)
from episodic.orchestration import WorkflowCheckpoint

if typ.TYPE_CHECKING:
    import collections.abc as cabc

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def _checkpoint(
    *,
    checkpoint_id: str | None = None,
    idempotency_key: str | None = None,
) -> WorkflowCheckpoint:
    """Return a deterministic checkpoint fixture."""
    return WorkflowCheckpoint(
        checkpoint_id=checkpoint_id or str(uuid.uuid4()),
        workflow_id="corr-storage",
        workflow_type="generation_orchestration",
        step_name="execute",
        idempotency_key=(
            idempotency_key
            or "corr-storage:generation_orchestration:execute:action-1:0"
        ),
        payload={
            "request": {"correlation_id": "corr-storage"},
            "planner_result": {"plan": {"steps": []}},
        },
    )


_short_delays = st.sampled_from((0.0, 0.001, 0.005))


class _RecordingMetrics:
    """Capture checkpoint metrics for adapter assertions."""

    def __init__(self) -> None:
        self.counters: list[tuple[str, dict[str, str]]] = []
        self.latencies: list[tuple[str, float, dict[str, str]]] = []

    def increment_counter(
        self,
        name: str,
        *,
        labels: cabc.Mapping[str, str],
    ) -> None:
        """Record a counter increment."""
        self.counters.append((name, dict(labels)))

    def observe_latency_ms(
        self,
        name: str,
        value: float,
        *,
        labels: cabc.Mapping[str, str],
    ) -> None:
        """Record a latency observation."""
        self.latencies.append((name, value, dict(labels)))


class _StepClock:
    """Deterministic monotonic clock for metric latency assertions."""

    def __init__(self) -> None:
        self._seconds = 0.0

    def monotonic_seconds(self) -> float:
        """Return a timestamp that advances by 1 ms on each call."""
        self._seconds += 0.001
        return self._seconds


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
async def test_checkpoint_store_records_checkpoint_metrics(
    session_factory: object,
) -> None:
    """Checkpoint operations should record bounded outcome and latency metrics."""
    factory = typ.cast("async_sessionmaker[AsyncSession]", session_factory)
    metrics = _RecordingMetrics()
    key = "corr-storage:generation_orchestration:execute:metrics:0"
    checkpoint = _checkpoint(idempotency_key=key)
    duplicate = _checkpoint(checkpoint_id=str(uuid.uuid4()), idempotency_key=key)

    async with factory() as session:
        store = SqlAlchemyWorkflowCheckpointStore(
            session,
            metrics=metrics,
            clock=_StepClock(),
        )
        first = await store.save_or_reuse(checkpoint)
        second = await store.save_or_reuse(duplicate)
        await session.commit()

    async with SqlAlchemyUnitOfWork(factory) as uow:
        stored = await uow.workflow_checkpoints.save_or_reuse(_checkpoint())
        await uow.commit()

    async with factory() as session:
        store = SqlAlchemyWorkflowCheckpointStore(
            session,
            metrics=metrics,
            clock=_StepClock(),
        )
        await store.mark_resumed(stored.checkpoint_id)
        with pytest.raises(ValueError, match="unknown checkpoint"):
            await store.mark_resumed(str(uuid.uuid4()))
        await session.rollback()

    assert second.checkpoint_id == first.checkpoint_id
    assert metrics.counters == [
        (
            "workflow_checkpoint.save_or_reuse.operations",
            {"outcome": "persisted"},
        ),
        (
            "workflow_checkpoint.save_or_reuse.idempotency_conflicts",
            {"outcome": "conflict"},
        ),
        ("workflow_checkpoint.save_or_reuse.operations", {"outcome": "reused"}),
        ("workflow_checkpoint.mark_resumed.operations", {"outcome": "marked"}),
        (
            "workflow_checkpoint.mark_resumed.operations",
            {"outcome": "unknown_checkpoint"},
        ),
    ]
    assert [(name, labels) for name, _value, labels in metrics.latencies] == [
        (
            "workflow_checkpoint.save_or_reuse.latency_ms",
            {"outcome": "persisted"},
        ),
        ("workflow_checkpoint.save_or_reuse.latency_ms", {"outcome": "reused"}),
        ("workflow_checkpoint.mark_resumed.latency_ms", {"outcome": "marked"}),
        (
            "workflow_checkpoint.mark_resumed.latency_ms",
            {"outcome": "unknown_checkpoint"},
        ),
    ]
    assert all(value > 0 for _name, value, _labels in metrics.latencies)


@pytest.mark.asyncio
async def test_checkpoint_store_reuses_concurrent_idempotency_key(
    session_factory: object,
) -> None:
    """Concurrent saves with one step key should persist one checkpoint."""
    factory = typ.cast("async_sessionmaker[AsyncSession]", session_factory)
    key = "corr-storage:generation_orchestration:execute:action-2:0"
    first = _checkpoint(checkpoint_id=str(uuid.uuid4()), idempotency_key=key)
    duplicate = _checkpoint(checkpoint_id=str(uuid.uuid4()), idempotency_key=key)

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
    checkpoint = _checkpoint()

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
    first = _checkpoint(checkpoint_id=str(uuid.uuid4()), idempotency_key=key)
    duplicate = _checkpoint(checkpoint_id=str(uuid.uuid4()), idempotency_key=key)

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
    checkpoint = _checkpoint(idempotency_key=f"prop:{uuid.uuid4()}:resume")
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
