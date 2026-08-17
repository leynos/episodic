"""Generation-run execution-claim SQLAlchemy adapter contract tests."""

import asyncio
import datetime as dt
import typing as typ
import uuid

import pytest

from episodic.canonical.domain import GenerationRun, GenerationRunStatus
from episodic.canonical.generation_run_errors import RunAlreadyTerminal, RunNotFound
from episodic.canonical.generation_run_ports import GenerationRunStatusUpdate
from episodic.canonical.storage import SqlAlchemyUnitOfWork
from episodic.canonical.storage import generation_runs as generation_runs_module
from tests.canonical_storage._generation_run_support import (
    NOW,
    claim_run_in_independent_uow,
    make_generation_run,
    persist_generation_run_prerequisites,
)

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


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
            current_node=current_node,
            started_at=NOW,
            lease_expires_at=lease_expires_at,
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
async def test_generation_run_store_logs_claim_outcomes(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Claim outcomes should emit bounded structured operational fields."""
    pending_run = make_generation_run()
    terminal_run = make_generation_run()
    lease_expires_at = NOW + dt.timedelta(minutes=5)
    await persist_generation_run_prerequisites(
        session_factory,
        pending_run,
        terminal_run,
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
        current_node="draft",
        started_at=NOW,
        lease_expires_at=lease_expires_at,
    )
    lost = await claim_run_in_independent_uow(
        session_factory,
        pending_run.id,
        current_node="draft",
        started_at=NOW,
        lease_expires_at=lease_expires_at,
    )

    missing_run_id = uuid.uuid7()
    with pytest.raises(RunNotFound):
        await claim_run_in_independent_uow(
            session_factory,
            missing_run_id,
            current_node="draft",
            started_at=NOW,
            lease_expires_at=lease_expires_at,
        )

    with pytest.raises(RunAlreadyTerminal):
        await claim_run_in_independent_uow(
            session_factory,
            terminal_run.id,
            current_node="draft",
            started_at=NOW,
            lease_expires_at=lease_expires_at,
        )

    assert claimed is not None, f"expected pending run {pending_run.id} to be claimed"
    assert lost is None, f"expected second claim to lose, got {lost!r}"
    events_by_name = {
        message: (level, fields) for level, message, fields in events
    }
    assert len(events_by_name) == len(events) == 4, events
    assert events_by_name["sql_generation_run_store.claim_run"] == (
        "info",
        {
            "run_id": str(pending_run.id),
            "current_node": "draft",
            "lease_expires_at": lease_expires_at.isoformat(),
        },
    ), events
    assert events_by_name["sql_generation_run_store.claim_run_lost"] == (
        "info",
        {"run_id": str(pending_run.id), "status": "running"},
    ), events
    assert events_by_name["sql_generation_run_store.claim_run_missing"] == (
        "warning",
        {"run_id": str(missing_run_id)},
    ), events
    assert events_by_name["sql_generation_run_store.claim_run_terminal"] == (
        "warning",
        {"run_id": str(terminal_run.id), "status": "succeeded"},
    ), events
