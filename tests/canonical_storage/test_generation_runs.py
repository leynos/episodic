"""Generation-run SQLAlchemy adapter contract tests.

These tests exercise durable generation-run and event-log persistence through
`SqlAlchemyUnitOfWork.generation_runs` and the concrete
`SqlAlchemyGenerationRunStore`. They cover run round-trips, idempotency,
event sequence allocation, terminal immutability, and transaction rollback.
"""

import dataclasses as dc
import datetime as dt
import typing as typ
import uuid

import pytest

from episodic.canonical.domain import GenerationRunStatus
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
from tests.canonical_storage._generation_run_support import (
    NOW,
    count_records,
    make_generation_run,
    persist_generation_run_prerequisites,
)

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@pytest.mark.asyncio
async def test_generation_run_store_satisfies_run_and_event_ports(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The SQLAlchemy adapter should implement run repository and event log."""
    async with session_factory() as session:
        store = SqlAlchemyGenerationRunStore(session)

    assert isinstance(store, GenerationRunRepository), f"store type: {type(store)}"
    assert isinstance(store, GenerationEventLog), f"store type: {type(store)}"


@pytest.mark.asyncio
async def test_generation_run_store_persists_across_unit_of_work(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Runs and events should survive fresh unit-of-work instances."""
    run = make_generation_run()
    await persist_generation_run_prerequisites(session_factory, run)

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
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

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        fetched = await uow.generation_runs.get_run(run.id)
        events = await uow.generation_runs.list_events(run.id)

    assert fetched == stored, f"expected stored run {stored!r}, got {fetched!r}"
    assert fetched is not None, f"expected run {run.id} to persist, got {fetched!r}"
    assert fetched.quality_mode is QualityMode.DRAFT_WITHOUT_QA, (
        f"expected draft-without-QA quality mode, got {fetched.quality_mode!r}"
    )
    assert fetched.qa_status is QaStatus.SKIPPED, f"QA status: {fetched.qa_status}"
    assert fetched.skip_qa_rationale == "No-QA vertical-slice draft.", (
        f"unexpected skip-QA rationale: {fetched.skip_qa_rationale!r}"
    )
    assert events == (first_event,), f"stored events: {events!r}"
    assert events[0].seq == 1, f"expected first event sequence 1, got {events[0].seq}"


@pytest.mark.asyncio
async def test_generation_run_store_reuses_idempotency_key(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A retried idempotency key should return the first stored run."""
    first = make_generation_run()
    duplicate = make_generation_run()
    await persist_generation_run_prerequisites(session_factory, first, duplicate)

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        stored_first = await uow.generation_runs.create_run(
            first,
            idempotency_key="same-key",
        )
        await uow.commit()

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        stored_duplicate = await uow.generation_runs.create_run(
            duplicate,
            idempotency_key="same-key",
        )
        await uow.commit()

    assert stored_duplicate == stored_first, f"duplicate run: {stored_duplicate.id}"
    record_count = await count_records(session_factory, GenerationRunRecord)
    assert record_count == 1, f"expected one generation run, got {record_count}"


@pytest.mark.asyncio
async def test_generation_events_allocate_gap_free_sequences_per_run(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Each run should own a gap-free event sequence starting at 1."""
    first_run = make_generation_run()
    second_run = make_generation_run()
    await persist_generation_run_prerequisites(session_factory, first_run, second_run)

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
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

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        first_events = await uow.generation_runs.list_events(first_run.id)
        second_events = await uow.generation_runs.list_events(second_run.id)
        after_first = await uow.generation_runs.list_events(
            first_run.id,
            after_seq=event_seq(1),
        )

    assert [event.seq for event in first_events] == [event_seq(1), event_seq(2)], (
        f"expected first-run sequences [1, 2], got {first_events!r}"
    )
    assert [event.seq for event in second_events] == [event_seq(1)], (
        f"expected second-run sequence [1], got {second_events!r}"
    )
    assert after_first == (second_event,), (
        f"expected event after sequence 1 to be {second_event!r}, got {after_first!r}"
    )
    assert first_events == (first_event, second_event), (
        f"unexpected first-run events: {first_events!r}"
    )
    assert second_events == (other_run_event,), (
        f"unexpected second-run events: {second_events!r}"
    )
    event_count = await count_records(session_factory, GenerationEventRecord)
    assert event_count == 3, f"expected three generation events, got {event_count}"


@pytest.mark.asyncio
async def test_generation_run_store_updates_status_and_rejects_terminal_mutation(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Status updates should persist and terminal runs should be immutable."""
    run = make_generation_run()
    await persist_generation_run_prerequisites(session_factory, run)

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
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

    assert running.status is GenerationRunStatus.RUNNING, (
        f"expected running status, got {running.status!r}"
    )
    assert running.current_node == "draft", (
        f"expected current node 'draft', got {running.current_node!r}"
    )
    assert succeeded.status is GenerationRunStatus.SUCCEEDED, (
        f"expected succeeded status, got {succeeded.status!r}"
    )
    assert succeeded.ended_at == NOW, (
        f"expected end time {NOW!r}, got {succeeded.ended_at!r}"
    )

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
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
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The execution claim should be a guarded pending-to-running transition."""
    run = make_generation_run()
    lease_expires_at = NOW + dt.timedelta(minutes=5)
    await persist_generation_run_prerequisites(session_factory, run)

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        await uow.generation_runs.create_run(run)
        await uow.commit()

    async with SqlAlchemyUnitOfWork(session_factory) as first_uow:
        claimed = await first_uow.generation_runs.claim_run_for_execution(
            run.id,
            current_node="draft",
            started_at=NOW,
            lease_expires_at=lease_expires_at,
        )
        await first_uow.commit()

    async with SqlAlchemyUnitOfWork(session_factory) as second_uow:
        lost = await second_uow.generation_runs.claim_run_for_execution(
            run.id,
            current_node="draft",
            started_at=NOW,
            lease_expires_at=lease_expires_at,
        )

    assert claimed is not None, f"expected run {run.id} to be claimed, got {claimed!r}"
    assert claimed.status is GenerationRunStatus.RUNNING, (
        f"expected claimed run to be running, got {claimed.status!r}"
    )
    assert claimed.current_node == "draft", (
        f"expected claimed node 'draft', got {claimed.current_node!r}"
    )
    assert claimed.started_at == NOW, (
        f"expected claim start {NOW!r}, got {claimed.started_at!r}"
    )
    assert lost is None, f"expected second claim to lose, got {lost!r}"


@pytest.mark.asyncio
async def test_generation_run_store_lists_runs_by_episode_status_and_page(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Run listing should be ordered, paged, and filterable by status."""
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
    await persist_generation_run_prerequisites(
        session_factory,
        first,
        running,
        other_episode,
    )

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        await uow.generation_runs.create_run(first)
        await uow.generation_runs.create_run(running)
        await uow.generation_runs.create_run(other_episode)
        await uow.commit()

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        page = await uow.generation_runs.list_runs(episode_id, limit=1, offset=1)
        running_only = await uow.generation_runs.list_runs(
            episode_id,
            status=GenerationRunStatus.RUNNING,
        )

    assert page == (running,), f"expected second paged run {running.id}, got {page!r}"
    assert running_only == (running,), (
        f"expected only running run {running.id}, got {running_only!r}"
    )


@pytest.mark.asyncio
async def test_generation_run_store_rejects_negative_limit(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """SQL-backed run listing should reject negative limits."""
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        with pytest.raises(ValueError, match="limit"):
            await uow.generation_runs.list_runs(uuid.uuid7(), limit=-1)


@pytest.mark.asyncio
async def test_generation_run_store_rejects_negative_offset(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """SQL-backed run listing should reject negative offsets."""
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        with pytest.raises(ValueError, match="offset"):
            await uow.generation_runs.list_runs(uuid.uuid7(), offset=-1)


@pytest.mark.asyncio
async def test_generation_run_store_rolls_back_uncommitted_run(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Uncommitted runs should not survive unit-of-work rollback."""
    run = make_generation_run()
    await persist_generation_run_prerequisites(session_factory, run)

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        await uow.generation_runs.create_run(run)
        await uow.rollback()

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        fetched = await uow.generation_runs.get_run(run.id)

    assert fetched is None, f"expected rolled-back run to be absent, got {fetched!r}"
