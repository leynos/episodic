"""Generation-run execution-claim SQLAlchemy adapter contract tests."""

import asyncio
import dataclasses as dc
import datetime as dt
import typing as typ
import uuid

import pytest
import sqlalchemy as sa

from episodic.canonical.domain import GenerationRun, GenerationRunStatus
from episodic.canonical.generation_run_errors import RunAlreadyTerminal, RunNotFound
from episodic.canonical.generation_run_ports import GenerationRunStatusUpdate
from episodic.canonical.storage import SqlAlchemyUnitOfWork
from episodic.canonical.storage import generation_runs as generation_runs_module
from episodic.canonical.storage.generation_run_models import GenerationRunRecord
from episodic.canonical.storage.generation_runs import SqlAlchemyGenerationRunStore
from tests.canonical_storage._generation_run_support import (
    NOW,
    ExecutionClaim,
    claim_run_in_independent_uow,
    make_generation_run,
    persist_generation_run_prerequisites,
)

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@dc.dataclass(frozen=True, slots=True)
class _ClaimOutcomeLogExpectations:
    """Expected identifiers and lease timestamp for claim-outcome logs."""

    pending_run_id: uuid.UUID
    missing_run_id: uuid.UUID
    terminal_run_id: uuid.UUID
    lease_expires_at: dt.datetime


async def _manually_fail_expired_run(
    session_factory: async_sessionmaker[AsyncSession],
    run_id: uuid.UUID,
    *,
    now: dt.datetime,
) -> bool:
    """Apply the documented manual-recovery transaction for one run."""
    async with session_factory() as session:
        record = await session.scalar(
            sa
            .select(GenerationRunRecord)
            .where(
                GenerationRunRecord.id == run_id,
                GenerationRunRecord.status == GenerationRunStatus.RUNNING,
                GenerationRunRecord.lease_expires_at.is_not(None),
                GenerationRunRecord.lease_expires_at <= now,
            )
            .with_for_update()
        )
        if record is None:
            await session.rollback()
            return False

        store = SqlAlchemyGenerationRunStore(session)
        await store.append_event(
            run_id,
            kind="run.failed",
            payload={
                "error_category": "launcher.lease_expired",
                "error_message": "Generation lease expired; failed manually.",
            },
            occurred_at=now,
        )
        await store.update_run_status(
            run_id,
            update=GenerationRunStatusUpdate(
                status=GenerationRunStatus.FAILED,
                current_node=None,
                ended_at=now,
                error_message="Generation lease expired; failed manually.",
                error_category="launcher.lease_expired",
            ),
        )
        await session.commit()
        return True


async def _assert_manual_recovery_state(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    expired_run_id: uuid.UUID,
    non_expired_run_id: uuid.UUID,
    terminal_run_id: uuid.UUID,
) -> None:
    """Assert that only the expired run was recovered."""
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        expired = await uow.generation_runs.get_run(expired_run_id)
        non_expired = await uow.generation_runs.get_run(non_expired_run_id)
        terminal = await uow.generation_runs.get_run(terminal_run_id)
        expired_events = await uow.generation_runs.list_events(expired_run_id)
        non_expired_events = await uow.generation_runs.list_events(non_expired_run_id)
        terminal_events = await uow.generation_runs.list_events(terminal_run_id)

    assert expired is not None, "expired run was not persisted"
    assert expired.status is GenerationRunStatus.FAILED, (
        f"expired run recovery state: {expired!r}"
    )
    assert expired.error_category == "launcher.lease_expired", (
        f"expired run failure category: {expired!r}"
    )
    assert [event.kind for event in expired_events] == ["run.failed"], (
        f"expired run recovery events: {expired_events!r}"
    )
    assert non_expired is not None, "non-expired run was not persisted"
    assert non_expired.status is GenerationRunStatus.RUNNING, (
        f"non-expired run recovery state: {non_expired!r}"
    )
    assert terminal is not None, "terminal run was not persisted"
    assert terminal.status is GenerationRunStatus.SUCCEEDED, (
        f"terminal run recovery state: {terminal!r}"
    )
    assert non_expired_events == (), (
        f"non-expired recovery must not append events: {non_expired_events!r}"
    )
    assert terminal_events == (), (
        f"terminal recovery must not append events: {terminal_events!r}"
    )


def _assert_claim_outcome_logs(
    events: list[tuple[str, str, dict[str, object]]],
    expected: _ClaimOutcomeLogExpectations,
) -> None:
    """Assert the ordered structured-log contract for every claim outcome."""
    observed_event_names = [message for _, message, _ in events]
    assert observed_event_names == [
        "sql_generation_run_store.claim_run",
        "sql_generation_run_store.claim_run_lost",
        "sql_generation_run_store.claim_run_missing",
        "sql_generation_run_store.claim_run_terminal",
    ], events
    events_by_name = {message: (level, fields) for level, message, fields in events}
    assert len(events_by_name) == len(events) == 4, events
    claimed_log = events_by_name["sql_generation_run_store.claim_run"]
    assert claimed_log[0] == "info", events
    assert claimed_log[1]["run_id"] == str(expected.pending_run_id), events
    assert claimed_log[1]["current_node"] == "draft", events
    assert (
        claimed_log[1]["lease_expires_at"] == expected.lease_expires_at.isoformat()
    ), events
    assert events_by_name["sql_generation_run_store.claim_run_lost"] == (
        "info",
        {"run_id": str(expected.pending_run_id), "status": "running"},
    ), events
    assert events_by_name["sql_generation_run_store.claim_run_missing"] == (
        "warning",
        {"run_id": str(expected.missing_run_id)},
    ), events
    assert events_by_name["sql_generation_run_store.claim_run_terminal"] == (
        "warning",
        {"run_id": str(expected.terminal_run_id), "status": "succeeded"},
    ), events


@pytest.mark.asyncio
async def test_generation_run_store_claims_pending_run_once_concurrently(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Two coordinated sessions should produce one winner and one lost claim."""
    run = make_generation_run()
    lease_expires_at = NOW + dt.timedelta(minutes=5)
    claim_barrier = asyncio.Barrier(2)
    await persist_generation_run_prerequisites(session_factory, run)

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        await uow.generation_runs.create_run(run)
        await uow.commit()

    async def claim_from_independent_session(
        current_node: str,
    ) -> GenerationRun | None:
        await claim_barrier.wait()
        return await claim_run_in_independent_uow(
            session_factory,
            run.id,
            ExecutionClaim(
                current_node=current_node,
                started_at=NOW,
                lease_expires_at=lease_expires_at,
            ),
        )

    claims = await asyncio.gather(
        claim_from_independent_session("draft-a"),
        claim_from_independent_session("draft-b"),
    )

    running_claims = [claim for claim in claims if claim is not None]
    assert len(running_claims) == 1, f"expected one running claim, got {claims!r}"
    assert sum(claim is None for claim in claims) == 1, (
        f"expected one lost claim, got {claims!r}"
    )
    assert running_claims[0].status is GenerationRunStatus.RUNNING, (
        f"expected running claim, got {running_claims[0]!r}"
    )

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        persisted = await uow.generation_runs.get_run(run.id)

    assert persisted is not None, f"expected persisted run {run.id}, got {persisted!r}"
    assert persisted.status is GenerationRunStatus.RUNNING, (
        f"expected persisted running state, got {persisted.status!r}"
    )


@pytest.mark.asyncio
async def test_manual_recovery_only_fails_expired_running_leases(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Manual recovery rolls back non-qualifying rows without appending events."""
    expired_run = make_generation_run()
    non_expired_run = make_generation_run()
    terminal_run = make_generation_run()
    await persist_generation_run_prerequisites(
        session_factory,
        expired_run,
        non_expired_run,
        terminal_run,
    )

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        for run in (expired_run, non_expired_run, terminal_run):
            await uow.generation_runs.create_run(run)
        await uow.commit()

    for run, lease_expires_at in (
        (expired_run, NOW - dt.timedelta(seconds=1)),
        (non_expired_run, NOW + dt.timedelta(seconds=1)),
    ):
        claimed = await claim_run_in_independent_uow(
            session_factory,
            run.id,
            ExecutionClaim(
                current_node="draft",
                started_at=NOW,
                lease_expires_at=lease_expires_at,
            ),
        )
        assert claimed is not None, f"expected running claim for {run.id}"

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        await uow.generation_runs.update_run_status(
            terminal_run.id,
            update=GenerationRunStatusUpdate(
                status=GenerationRunStatus.SUCCEEDED,
                current_node=None,
                ended_at=NOW,
            ),
        )
        await uow.commit()

    recovered = [
        await _manually_fail_expired_run(session_factory, expired_run.id, now=NOW),
        await _manually_fail_expired_run(
            session_factory,
            non_expired_run.id,
            now=NOW,
        ),
        await _manually_fail_expired_run(session_factory, terminal_run.id, now=NOW),
    ]
    assert recovered == [True, False, False], f"manual recovery results: {recovered!r}"

    await _assert_manual_recovery_state(
        session_factory,
        expired_run_id=expired_run.id,
        non_expired_run_id=non_expired_run.id,
        terminal_run_id=terminal_run.id,
    )


@pytest.mark.asyncio
async def test_generation_run_store_logs_claim_outcomes(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Claim outcomes should emit bounded structured operational fields."""
    pending_run = make_generation_run()
    terminal_run = make_generation_run()
    lease_expires_at = NOW + dt.timedelta(minutes=5)
    execution_claim = ExecutionClaim(
        current_node="draft",
        started_at=NOW,
        lease_expires_at=lease_expires_at,
    )
    await persist_generation_run_prerequisites(
        session_factory, pending_run, terminal_run
    )
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        await uow.generation_runs.create_run(pending_run)
        await uow.generation_runs.create_run(terminal_run)
        await uow.generation_runs.update_run_status(
            terminal_run.id,
            update=GenerationRunStatusUpdate(
                status=GenerationRunStatus.SUCCEEDED,
                current_node=None,
                ended_at=NOW,
            ),
        )
        await uow.commit()
    events: list[tuple[str, str, dict[str, object]]] = []

    def capture_log_event(level: str, message: str, **fields: object) -> None:
        events.append((level, message, fields))

    monkeypatch.setattr(generation_runs_module, "_log_event", capture_log_event)
    claimed = await claim_run_in_independent_uow(
        session_factory,
        pending_run.id,
        execution_claim,
    )
    lost = await claim_run_in_independent_uow(
        session_factory,
        pending_run.id,
        execution_claim,
    )

    missing_run_id = uuid.uuid7()
    with pytest.raises(RunNotFound):
        await claim_run_in_independent_uow(
            session_factory,
            missing_run_id,
            execution_claim,
        )

    with pytest.raises(RunAlreadyTerminal):
        await claim_run_in_independent_uow(
            session_factory,
            terminal_run.id,
            execution_claim,
        )

    assert claimed is not None, f"expected pending run {pending_run.id} to be claimed"
    assert lost is None, f"expected second claim to lose, got {lost!r}"
    expected = _ClaimOutcomeLogExpectations(
        pending_run_id=pending_run.id,
        missing_run_id=missing_run_id,
        terminal_run_id=terminal_run.id,
        lease_expires_at=lease_expires_at,
    )
    _assert_claim_outcome_logs(events, expected)
