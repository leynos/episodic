"""Transition and ordering coverage for expired-lease reclamation.

The state partition -- *which* runs the primitive selects -- is asserted in
``test_generation_run_lease_reclamation.py``. This module covers what the
primitive writes once a run is selected: the single instant recorded across the
event, ``ended_at``, and ``updated_at``; the append-before-update order the
event log's mutability rule forces; idempotence; and the batch semantics of
``limit``, including draining a backlog in ``(lease_expires_at, id)`` order.
"""

import datetime as dt
import typing as typ

import pytest

from episodic.canonical.generation_run_errors import RunAlreadyTerminal
from episodic.canonical.storage import SqlAlchemyUnitOfWork
from episodic.canonical.storage import generation_runs as generation_runs_module
from tests.canonical_storage._generation_run_lease_support import (
    EXPIRED_LEASE,
    claimed_expired_run,
    reclaim,
)
from tests.canonical_storage._generation_run_support import NOW

if typ.TYPE_CHECKING:
    import uuid

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from episodic.canonical.domain import (
        GenerationEvent,
        GenerationRun,
        JsonMapping,
    )
    from episodic.canonical.generation_run_ports import GenerationRunStatusUpdate
    from episodic.canonical.storage.generation_runs import (
        SqlAlchemyGenerationRunStore,
    )


@pytest.mark.asyncio
async def test_reclamation_writes_the_shared_instant_everywhere(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """``now`` drives the event timestamp as well as the persisted timestamps."""
    run = await claimed_expired_run(session_factory)
    later = NOW + dt.timedelta(hours=1)

    reclaimed = await reclaim(session_factory, now=later)

    assert [item.id for item in reclaimed] == [run.id], reclaimed
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        events = await uow.generation_runs.list_events(run.id)
    assert events[0].occurred_at == later, events
    assert reclaimed[0].ended_at == later, reclaimed[0]
    assert reclaimed[0].updated_at == later, reclaimed[0]


@pytest.mark.asyncio
async def test_reclamation_appends_the_event_before_the_terminal_update(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The event append precedes the status update, and must.

    A run's event stream closes when the run ends, so appending afterwards is
    rejected. The reverse implementation type-checks cleanly, which is why the
    order is asserted here rather than left to inspection.
    """
    run = await claimed_expired_run(session_factory)
    calls: list[str] = []
    real_append = generation_runs_module.SqlAlchemyGenerationRunStore.append_event
    real_update = generation_runs_module.SqlAlchemyGenerationRunStore.update_run_status

    # Pylint strips `self` only for real methods, so this stand-in is measured
    # one argument above the identical store method it mirrors.
    # pylint: disable-next=too-many-arguments
    async def recording_append(
        self: SqlAlchemyGenerationRunStore,
        run_id: uuid.UUID,
        *,
        kind: str,
        payload: JsonMapping,
        occurred_at: dt.datetime | None = None,
    ) -> GenerationEvent:
        calls.append("append_event")
        return await real_append(
            self,
            run_id,
            kind=kind,
            payload=payload,
            occurred_at=occurred_at,
        )

    async def recording_update(
        self: SqlAlchemyGenerationRunStore,
        run_id: uuid.UUID,
        *,
        update: GenerationRunStatusUpdate,
    ) -> GenerationRun:
        calls.append("update_run_status")
        return await real_update(self, run_id, update=update)

    monkeypatch.setattr(
        generation_runs_module.SqlAlchemyGenerationRunStore,
        "append_event",
        recording_append,
    )
    monkeypatch.setattr(
        generation_runs_module.SqlAlchemyGenerationRunStore,
        "update_run_status",
        recording_update,
    )

    await reclaim(session_factory)

    assert calls == ["append_event", "update_run_status"], calls
    # The ordering is load bearing: the reverse order raises, so a future
    # refactor that reorders these calls cannot pass by accident.
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        with pytest.raises(RunAlreadyTerminal):
            await uow.generation_runs.append_event(
                run.id,
                kind="run.failed",
                payload={},
            )


@pytest.mark.asyncio
async def test_reclamation_is_idempotent(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A second invocation reclaims nothing and appends no second event."""
    run = await claimed_expired_run(session_factory)

    first = await reclaim(session_factory)
    second = await reclaim(session_factory)

    assert [item.id for item in first] == [run.id], first
    assert second == (), second
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        events = await uow.generation_runs.list_events(run.id)
    assert [event.kind for event in events] == ["run.failed"], events


@pytest.mark.asyncio
async def test_reclamation_drains_a_backlog_in_expiry_order(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A limit truncates the backlog, and re-invocation reaches the rest.

    Two runs share a lease so the ``(lease_expires_at, id)`` tiebreak decides
    their relative order; the third holds an older lease and so must come
    first, in the first batch, regardless of identifier ordering.
    """
    shared_lease = EXPIRED_LEASE
    oldest_lease = EXPIRED_LEASE - dt.timedelta(minutes=1)
    oldest = await claimed_expired_run(
        session_factory,
        lease_expires_at=oldest_lease,
    )
    tied = [
        await claimed_expired_run(session_factory, lease_expires_at=shared_lease)
        for _ in range(2)
    ]
    expected = [oldest.id, *sorted(run.id for run in tied)]

    batches: list[list[uuid.UUID]] = []
    for _ in range(3):
        batch = await reclaim(session_factory, limit=2)
        batches.append([run.id for run in batch])

    assert batches[0] == expected[:2], batches
    assert batches[1] == expected[2:], batches
    assert batches[2] == [], batches
