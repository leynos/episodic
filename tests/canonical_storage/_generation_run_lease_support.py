"""Shared support for the expired-lease reclamation tests.

The reclamation primitive is exercised from two angles that share almost all of
their setup: the state partition it selects
(``test_generation_run_lease_reclamation.py``) and the transition it writes
(``test_generation_run_lease_transitions.py``). The seeding, invocation, and
expected-payload definitions those two suites agree on live here, so neither
suite has to import the other's fixtures.
"""

import datetime as dt
import typing as typ
import uuid

from episodic.canonical.domain import (
    Checkpoint,
    CheckpointStatus,
    GenerationRun,
    GenerationRunStatus,
)
from episodic.canonical.generation_run_ports import GenerationRunStatusUpdate
from episodic.canonical.storage import SqlAlchemyUnitOfWork
from tests.canonical_storage._generation_run_support import (
    NOW,
    ExecutionClaim,
    claim_run_in_independent_uow,
    make_generation_run,
    persist_generation_run_prerequisites,
)

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

EXPIRED_LEASE = NOW - dt.timedelta(minutes=15)
FUTURE_LEASE = NOW + dt.timedelta(minutes=15)
LEASE_ERROR_CATEGORY = "launcher.lease_expired"
LEASE_ERROR_MESSAGE = "Generation lease expired; failed manually."


def checkpoint_for(run_id: uuid.UUID) -> Checkpoint:
    """Build an open checkpoint that suspends a run awaiting review."""
    return Checkpoint(
        id=uuid.uuid7(),
        generation_run_id=run_id,
        node="review",
        prompt="Approve the draft?",
        options=("approve", "request_changes"),
        status=CheckpointStatus.CREATED,
        created_at=NOW,
        responded_at=None,
        responded_by=None,
        response_action=None,
        response_payload={},
    )


async def create_runs(
    session_factory: async_sessionmaker[AsyncSession],
    runs: list[GenerationRun],
) -> None:
    """Commit prerequisite rows and the runs themselves."""
    await persist_generation_run_prerequisites(session_factory, *runs)
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        for run in runs:
            await uow.generation_runs.create_run(run)
        await uow.commit()


async def claim_run(
    session_factory: async_sessionmaker[AsyncSession],
    run_id: uuid.UUID,
    *,
    lease_expires_at: dt.datetime | None,
) -> None:
    """Move one committed run to ``running`` under the given lease.

    Raises
    ------
    AssertionError
        If the run is not claimable. Seeding a partition assumes every run
        starts claimable; an unclaimable one would silently drop that row from
        the state space the tests believe they are covering, so the misuse is
        reported rather than tolerated.
    """
    claimed = await claim_run_in_independent_uow(
        session_factory,
        run_id,
        ExecutionClaim(
            current_node="draft",
            started_at=NOW,
            lease_expires_at=lease_expires_at,
        ),
    )
    if claimed is None:
        msg = f"Run {run_id} was not claimable."
        raise AssertionError(msg)


async def end_run(
    session_factory: async_sessionmaker[AsyncSession],
    run_id: uuid.UUID,
    status: GenerationRunStatus,
) -> None:
    """Move one run to a terminal status through the lifecycle transition."""
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        await uow.generation_runs.update_run_status(
            run_id,
            update=GenerationRunStatusUpdate(
                status=status,
                current_node=None,
                ended_at=NOW,
            ),
        )
        await uow.commit()


async def claimed_expired_run(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    lease_expires_at: dt.datetime | None = None,
) -> GenerationRun:
    """Commit one run claimed under a lease that already expired."""
    run = make_generation_run()
    await create_runs(session_factory, [run])
    await claim_run(
        session_factory,
        run.id,
        lease_expires_at=lease_expires_at or EXPIRED_LEASE,
    )
    return run


async def reclaim(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    now: dt.datetime = NOW,
    limit: int = 100,
) -> tuple[GenerationRun, ...]:
    """Run one reclamation call through the port and commit it."""
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        reclaimed = await uow.generation_runs.fail_expired_leases(
            now=now,
            limit=limit,
        )
        await uow.commit()
    return reclaimed
