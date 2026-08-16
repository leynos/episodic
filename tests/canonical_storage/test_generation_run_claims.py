"""Generation-run execution-claim SQLAlchemy adapter contract tests."""

import asyncio
import datetime as dt
import uuid

import pytest

from episodic.canonical.domain import GenerationRun, GenerationRunStatus
from episodic.canonical.generation_run_errors import RunAlreadyTerminal, RunNotFound
from episodic.canonical.generation_run_ports import GenerationRunStatusUpdate
from episodic.canonical.storage import SqlAlchemyUnitOfWork
from episodic.canonical.storage import generation_runs as generation_runs_module
from tests.canonical_storage.test_generation_runs import (
    NOW,
    _factory,
    make_generation_run,
)


@pytest.mark.asyncio
async def test_generation_run_store_claims_pending_run_once_concurrently(
    session_factory: object,
) -> None:
    """Two coordinated sessions should produce one winner and one lost claim."""
    factory = _factory(session_factory)
    run = make_generation_run()
    lease_expires_at = NOW + dt.timedelta(minutes=5)
    claim_barrier = asyncio.Barrier(2)

    async with SqlAlchemyUnitOfWork(factory) as uow:
        await uow.generation_runs.create_run(run)
        await uow.commit()

    async def claim_from_independent_session(
        current_node: str,
    ) -> GenerationRun | None:
        async with SqlAlchemyUnitOfWork(factory) as uow:
            await claim_barrier.wait()
            claimed = await uow.generation_runs.claim_run_for_execution(
                run.id,
                current_node=current_node,
                started_at=NOW,
                lease_expires_at=lease_expires_at,
            )
            await uow.commit()
            return claimed

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

    async with SqlAlchemyUnitOfWork(factory) as uow:
        persisted = await uow.generation_runs.get_run(run.id)

    assert persisted is not None, f"expected persisted run {run.id}, got {persisted!r}"
    assert persisted.status is GenerationRunStatus.RUNNING, (
        f"expected persisted running state, got {persisted.status!r}"
    )


@pytest.mark.asyncio
async def test_generation_run_store_logs_claim_outcomes(
    session_factory: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Claim outcomes should emit bounded structured operational fields."""
    factory = _factory(session_factory)
    pending_run = make_generation_run()
    terminal_run = make_generation_run()
    lease_expires_at = NOW + dt.timedelta(minutes=5)

    async with SqlAlchemyUnitOfWork(factory) as uow:
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

    async with SqlAlchemyUnitOfWork(factory) as uow:
        claimed = await uow.generation_runs.claim_run_for_execution(
            pending_run.id,
            current_node="draft",
            started_at=NOW,
            lease_expires_at=lease_expires_at,
        )
        await uow.commit()

    async with SqlAlchemyUnitOfWork(factory) as uow:
        lost = await uow.generation_runs.claim_run_for_execution(
            pending_run.id,
            current_node="draft",
            started_at=NOW,
            lease_expires_at=lease_expires_at,
        )

    missing_run_id = uuid.uuid7()
    async with SqlAlchemyUnitOfWork(factory) as uow:
        with pytest.raises(RunNotFound):
            await uow.generation_runs.claim_run_for_execution(
                missing_run_id,
                current_node="draft",
                started_at=NOW,
                lease_expires_at=lease_expires_at,
            )

    async with SqlAlchemyUnitOfWork(factory) as uow:
        with pytest.raises(RunAlreadyTerminal):
            await uow.generation_runs.claim_run_for_execution(
                terminal_run.id,
                current_node="draft",
                started_at=NOW,
                lease_expires_at=lease_expires_at,
            )

    assert claimed is not None, f"expected pending run {pending_run.id} to be claimed"
    assert lost is None, f"expected second claim to lose, got {lost!r}"
    observed_event_names = [event[1] for event in events]
    assert observed_event_names == [
        "sql_generation_run_store.claim_run",
        "sql_generation_run_store.claim_run_lost",
        "sql_generation_run_store.claim_run_missing",
        "sql_generation_run_store.claim_run_terminal",
    ], events
    assert events[0][0] == "info", events
    assert events[0][2] == {
        "run_id": str(pending_run.id),
        "current_node": "draft",
        "lease_expires_at": lease_expires_at.isoformat(),
    }, events
    assert events[1] == (
        "info",
        "sql_generation_run_store.claim_run_lost",
        {"run_id": str(pending_run.id), "status": "running"},
    ), events
    assert events[2] == (
        "warning",
        "sql_generation_run_store.claim_run_missing",
        {"run_id": str(missing_run_id)},
    ), events
    assert events[3] == (
        "warning",
        "sql_generation_run_store.claim_run_terminal",
        {"run_id": str(terminal_run.id), "status": "succeeded"},
    ), events
