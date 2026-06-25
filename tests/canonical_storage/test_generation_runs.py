"""Generation-run SQLAlchemy adapter contract tests.

These tests exercise durable generation-run and event-log persistence through
`SqlAlchemyUnitOfWork.generation_runs` and the concrete
`SqlAlchemyGenerationRunStore`. They cover run round-trips, idempotency,
event sequence allocation, terminal immutability, and transaction rollback.
"""

from __future__ import annotations

import dataclasses as dc
import datetime as dt
import typing as typ
import uuid

import pytest
import sqlalchemy as sa

from episodic.canonical.domain import GenerationRun, GenerationRunStatus
from episodic.canonical.generation_quality import QaStatus, QualityMode
from episodic.canonical.generation_run_errors import RunAlreadyTerminal
from episodic.canonical.generation_run_ports import (
    GenerationEventLog,
    GenerationRunRepository,
    GenerationRunStatusUpdate,
    event_seq,
)
from episodic.canonical.storage import (
    GenerationEventRecord,
    GenerationRunRecord,
    SqlAlchemyGenerationRunStore,
    SqlAlchemyUnitOfWork,
)

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


NOW = dt.datetime(2026, 6, 24, 8, 30, tzinfo=dt.UTC)


def make_generation_run(
    *,
    run_id: uuid.UUID | None = None,
    episode_id: uuid.UUID | None = None,
    status: GenerationRunStatus = GenerationRunStatus.PENDING,
    created_at: dt.datetime = NOW,
) -> GenerationRun:
    """Build a no-QA generation run for storage tests."""
    return GenerationRun(
        id=run_id or uuid.uuid7(),
        episode_id=episode_id or uuid.uuid7(),
        source_bundle_id=uuid.uuid7(),
        actor="editor@example.com",
        status=status,
        current_node=None,
        budget_snapshot={"limit_usd": "5.00"},
        configuration={"quality_mode": QualityMode.DRAFT_WITHOUT_QA.value},
        created_at=created_at,
        updated_at=created_at,
        started_at=None,
        ended_at=None,
        error_message=None,
        quality_mode=QualityMode.DRAFT_WITHOUT_QA,
        qa_status=QaStatus.SKIPPED,
        skip_qa_rationale="No-QA vertical-slice draft.",
    )


def _factory(
    session_factory: object,
) -> async_sessionmaker[AsyncSession]:
    """Return the typed async session factory fixture."""
    return typ.cast("async_sessionmaker[AsyncSession]", session_factory)


async def _count_records(
    factory: async_sessionmaker[AsyncSession],
    record_type: type[object],
) -> int:
    """Count persisted records of one SQLAlchemy model type."""
    async with factory() as session:
        return await session.scalar(sa.select(sa.func.count()).select_from(record_type))


@pytest.mark.asyncio
async def test_generation_run_store_satisfies_run_and_event_ports(
    session_factory: object,
) -> None:
    """The SQLAlchemy adapter should implement run repository and event log."""
    factory = _factory(session_factory)

    async with factory() as session:
        store = SqlAlchemyGenerationRunStore(session)

    assert isinstance(store, GenerationRunRepository)
    assert isinstance(store, GenerationEventLog)


@pytest.mark.asyncio
async def test_generation_run_store_persists_across_unit_of_work(
    session_factory: object,
) -> None:
    """Runs and events should survive fresh unit-of-work instances."""
    factory = _factory(session_factory)
    run = make_generation_run()

    async with SqlAlchemyUnitOfWork(factory) as uow:
        stored = await uow.generation_runs.create_run(
            run,
            idempotency_key="persist-run",
        )
        first_event = await uow.generation_runs.append_event(
            stored.id,
            kind="generation_run.created",
            payload={"actor": stored.actor},
            occurred_at=NOW,
        )
        await uow.commit()

    async with SqlAlchemyUnitOfWork(factory) as uow:
        fetched = await uow.generation_runs.get_run(run.id)
        events = await uow.generation_runs.list_events(run.id)

    assert fetched == stored
    assert fetched is not None
    assert fetched.quality_mode is QualityMode.DRAFT_WITHOUT_QA
    assert fetched.qa_status is QaStatus.SKIPPED
    assert fetched.skip_qa_rationale == "No-QA vertical-slice draft."
    assert events == (first_event,)
    assert events[0].seq == 1


@pytest.mark.asyncio
async def test_generation_run_store_reuses_idempotency_key(
    session_factory: object,
) -> None:
    """A retried idempotency key should return the first stored run."""
    factory = _factory(session_factory)
    first = make_generation_run()
    duplicate = make_generation_run()

    async with SqlAlchemyUnitOfWork(factory) as uow:
        stored_first = await uow.generation_runs.create_run(
            first,
            idempotency_key="same-key",
        )
        await uow.commit()

    async with SqlAlchemyUnitOfWork(factory) as uow:
        stored_duplicate = await uow.generation_runs.create_run(
            duplicate,
            idempotency_key="same-key",
        )
        await uow.commit()

    assert stored_duplicate == stored_first
    assert await _count_records(factory, GenerationRunRecord) == 1


@pytest.mark.asyncio
async def test_generation_events_allocate_gap_free_sequences_per_run(
    session_factory: object,
) -> None:
    """Each run should own a gap-free event sequence starting at 1."""
    factory = _factory(session_factory)
    first_run = make_generation_run()
    second_run = make_generation_run()

    async with SqlAlchemyUnitOfWork(factory) as uow:
        await uow.generation_runs.create_run(first_run)
        await uow.generation_runs.create_run(second_run)
        first_event = await uow.generation_runs.append_event(
            first_run.id,
            kind="step.started",
            payload={"step": 1},
        )
        second_event = await uow.generation_runs.append_event(
            first_run.id,
            kind="step.finished",
            payload={"step": 1},
        )
        other_run_event = await uow.generation_runs.append_event(
            second_run.id,
            kind="step.started",
            payload={"step": 1},
        )
        await uow.commit()

    async with SqlAlchemyUnitOfWork(factory) as uow:
        first_events = await uow.generation_runs.list_events(first_run.id)
        second_events = await uow.generation_runs.list_events(second_run.id)
        after_first = await uow.generation_runs.list_events(
            first_run.id,
            after_seq=event_seq(1),
        )

    assert [event.seq for event in first_events] == [event_seq(1), event_seq(2)]
    assert [event.seq for event in second_events] == [event_seq(1)]
    assert after_first == (second_event,)
    assert first_events == (first_event, second_event)
    assert second_events == (other_run_event,)
    assert await _count_records(factory, GenerationEventRecord) == 3


@pytest.mark.asyncio
async def test_generation_run_store_updates_status_and_rejects_terminal_mutation(
    session_factory: object,
) -> None:
    """Status updates should persist and terminal runs should be immutable."""
    factory = _factory(session_factory)
    run = make_generation_run()

    async with SqlAlchemyUnitOfWork(factory) as uow:
        await uow.generation_runs.create_run(run)
        running = await uow.generation_runs.update_run_status(
            run.id,
            update=GenerationRunStatusUpdate(
                status=GenerationRunStatus.RUNNING,
                current_node="draft",
                ended_at=None,
            ),
        )
        succeeded = await uow.generation_runs.update_run_status(
            run.id,
            update=GenerationRunStatusUpdate(
                status=GenerationRunStatus.SUCCEEDED,
                current_node=None,
                ended_at=NOW,
            ),
        )
        await uow.commit()

    assert running.status is GenerationRunStatus.RUNNING
    assert running.current_node == "draft"
    assert succeeded.status is GenerationRunStatus.SUCCEEDED
    assert succeeded.ended_at == NOW

    async with SqlAlchemyUnitOfWork(factory) as uow:
        with pytest.raises(RunAlreadyTerminal, match="generation run is already"):
            await uow.generation_runs.update_run_status(
                run.id,
                update=GenerationRunStatusUpdate(
                    status=GenerationRunStatus.RUNNING,
                    current_node="retry",
                    ended_at=None,
                ),
            )
        with pytest.raises(RunAlreadyTerminal, match="generation run is already"):
            await uow.generation_runs.append_event(
                run.id,
                kind="retry.started",
                payload={},
            )


@pytest.mark.asyncio
async def test_generation_run_store_claims_pending_run_once(
    session_factory: object,
) -> None:
    """The execution claim should be a guarded pending-to-running transition."""
    factory = _factory(session_factory)
    run = make_generation_run()
    lease_expires_at = NOW + dt.timedelta(minutes=5)

    async with SqlAlchemyUnitOfWork(factory) as uow:
        await uow.generation_runs.create_run(run)
        await uow.commit()

    async with SqlAlchemyUnitOfWork(factory) as first_uow:
        claimed = await first_uow.generation_runs.claim_run_for_execution(
            run.id,
            current_node="draft",
            started_at=NOW,
            lease_expires_at=lease_expires_at,
        )
        await first_uow.commit()

    async with SqlAlchemyUnitOfWork(factory) as second_uow:
        lost = await second_uow.generation_runs.claim_run_for_execution(
            run.id,
            current_node="draft",
            started_at=NOW,
            lease_expires_at=lease_expires_at,
        )

    assert claimed is not None
    assert claimed.status is GenerationRunStatus.RUNNING
    assert claimed.current_node == "draft"
    assert claimed.started_at == NOW
    assert lost is None


@pytest.mark.asyncio
async def test_generation_run_store_lists_runs_by_episode_status_and_page(
    session_factory: object,
) -> None:
    """Run listing should be ordered, paged, and filterable by status."""
    factory = _factory(session_factory)
    episode_id = uuid.uuid7()
    first = make_generation_run(episode_id=episode_id, created_at=NOW)
    running = dc.replace(
        make_generation_run(
            episode_id=episode_id,
            created_at=NOW + dt.timedelta(seconds=1),
        ),
        status=GenerationRunStatus.RUNNING,
    )
    other_episode = make_generation_run(created_at=NOW + dt.timedelta(seconds=2))

    async with SqlAlchemyUnitOfWork(factory) as uow:
        await uow.generation_runs.create_run(first)
        await uow.generation_runs.create_run(running)
        await uow.generation_runs.create_run(other_episode)
        await uow.commit()

    async with SqlAlchemyUnitOfWork(factory) as uow:
        page = await uow.generation_runs.list_runs(episode_id, limit=1, offset=1)
        running_only = await uow.generation_runs.list_runs(
            episode_id,
            status=GenerationRunStatus.RUNNING,
        )

    assert page == (running,)
    assert running_only == (running,)


@pytest.mark.asyncio
async def test_generation_run_store_rolls_back_uncommitted_run(
    session_factory: object,
) -> None:
    """Uncommitted runs should not survive unit-of-work rollback."""
    factory = _factory(session_factory)
    run = make_generation_run()

    async with SqlAlchemyUnitOfWork(factory) as uow:
        await uow.generation_runs.create_run(run)
        await uow.rollback()

    async with SqlAlchemyUnitOfWork(factory) as uow:
        fetched = await uow.generation_runs.get_run(run.id)

    assert fetched is None
