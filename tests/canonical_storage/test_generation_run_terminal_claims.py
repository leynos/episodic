"""Durable terminal-claim contract tests for generation runs."""

import dataclasses as dc
import datetime as dt
import typing as typ
import uuid

import pytest

from episodic.canonical.domain import GenerationRunStatus
from episodic.canonical.generation_claim import ExecutionClaim
from episodic.canonical.generation_run_errors import (
    RunAlreadyTerminal,
    RunClaimMismatch,
)
from episodic.canonical.generation_run_ports import (
    GenerationRunStatusUpdate,
)
from episodic.canonical.storage import SqlAlchemyUnitOfWork
from tests.canonical_storage._generation_run_support import (
    NOW,
    make_generation_run,
    persist_generation_run_prerequisites,
)

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status",
    [
        GenerationRunStatus.SUCCEEDED,
        GenerationRunStatus.FAILED,
        GenerationRunStatus.CANCELLED,
    ],
)
async def test_sql_generation_run_claim_rejects_terminal_status(
    session_factory: async_sessionmaker[AsyncSession],
    status: GenerationRunStatus,
) -> None:
    """The SQL adapter raises rather than claiming any terminal run."""
    run = dc.replace(make_generation_run(), status=status, ended_at=NOW)
    await persist_generation_run_prerequisites(session_factory, run)
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        await uow.generation_runs.create_run(run)
        await uow.commit()

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        with pytest.raises(RunAlreadyTerminal, match="generation run is already"):
            await uow.generation_runs.claim_run_for_execution(
                run.id,
                ExecutionClaim(
                    current_node="draft",
                    started_at=NOW,
                    lease_expires_at=NOW + dt.timedelta(minutes=5),
                ),
            )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("current_node", "ended_at", "message"),
    [
        ("complete", NOW, "terminal generation runs must not have a current node"),
        (None, None, "terminal generation runs must have an end time"),
    ],
)
async def test_sql_generation_run_rejects_invalid_terminal_lifecycle(
    session_factory: async_sessionmaker[AsyncSession],
    current_node: str | None,
    ended_at: dt.datetime | None,
    message: str,
) -> None:
    """The SQL adapter validates terminal lifecycle fields before flushing."""
    run = make_generation_run()
    await persist_generation_run_prerequisites(session_factory, run)

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        await uow.generation_runs.create_run(run)
        with pytest.raises(ValueError, match=message):
            await uow.generation_runs.update_run_status(
                run.id,
                update=GenerationRunStatusUpdate(
                    status=GenerationRunStatus.SUCCEEDED,
                    current_node=current_node,
                    ended_at=ended_at,
                ),
            )
        await uow.commit()

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        stored = await uow.generation_runs.get_run(run.id)
    assert stored == run, "Invalid terminal update must not mutate the persisted run."


async def _claimed_run(
    session_factory: async_sessionmaker[AsyncSession],
) -> tuple[uuid.UUID, uuid.UUID]:
    """Persist a pending run and claim it, returning its id and proof."""
    run = make_generation_run()
    await persist_generation_run_prerequisites(session_factory, run)
    proof = uuid.uuid4()
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        await uow.generation_runs.create_run(run)
        await uow.generation_runs.claim_run_for_execution(
            run.id,
            ExecutionClaim(
                current_node="draft",
                started_at=NOW,
                lease_expires_at=None,
                claim_token=proof,
            ),
        )
        await uow.commit()
    return run.id, proof


def _success(claim_token: uuid.UUID | None) -> GenerationRunStatusUpdate:
    """Build a terminal success update carrying the given claim token."""
    return GenerationRunStatusUpdate(
        status=GenerationRunStatus.SUCCEEDED,
        current_node=None,
        ended_at=NOW,
        claim_token=claim_token,
    )


@pytest.mark.asyncio
async def test_a_terminal_write_requires_the_matching_claim(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A wrong or missing token cannot terminate a claimed run."""
    run_id, proof = await _claimed_run(session_factory)

    for supplied in (None, uuid.uuid4()):
        async with SqlAlchemyUnitOfWork(session_factory) as uow:
            with pytest.raises(RunClaimMismatch) as excinfo:
                await uow.generation_runs.update_run_status(
                    run_id,
                    update=_success(supplied),
                )
            await uow.rollback()
        assert str(run_id) in str(excinfo.value), excinfo.value
        async with SqlAlchemyUnitOfWork(session_factory) as uow:
            stored = await uow.generation_runs.get_run(run_id)
        assert stored is not None, "the rejected write must not remove the run"
        assert stored.status is GenerationRunStatus.RUNNING, stored.status

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        claimed = await uow.generation_runs.update_run_status(
            run_id,
            update=_success(proof),
        )
        await uow.commit()
    assert claimed.status is GenerationRunStatus.SUCCEEDED, claimed.status


@pytest.mark.asyncio
async def test_an_unclaimed_run_needs_no_token(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A run that was never claimed can still be failed by an internal path."""
    run = make_generation_run()
    await persist_generation_run_prerequisites(session_factory, run)
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        await uow.generation_runs.create_run(run)
        await uow.commit()

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        failed = await uow.generation_runs.update_run_status(
            run.id,
            update=GenerationRunStatusUpdate(
                status=GenerationRunStatus.FAILED,
                current_node=None,
                ended_at=NOW,
                error_message="launch failed",
                error_category="launcher.unavailable",
            ),
        )
        await uow.commit()
    assert failed.status is GenerationRunStatus.FAILED, failed.status
