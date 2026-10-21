"""State-partition coverage for the expired-lease reclamation primitive.

INV-LEASE-1 says a run is reclaimed only when it is ``running``, holds a
non-null lease that expired at or before the supplied instant, and has no
checkpoint in ``created``. Every case below is therefore a *selectivity* case:
the assertion is on the exact set of reclaimed identifiers, never a count, so a
primitive that reclaimed everything -- or nothing -- cannot pass by turning one
number into another.

``test_generation_run_lease_transitions.py`` owns the transition this primitive
writes once a run is selected; ``test_generation_run_claims.py`` and
``test_sql_generation_run_property_contract.py`` drive the same method from
their own angles.
"""

import dataclasses as dc
import typing as typ

import pytest

from episodic.canonical.domain import (
    GenerationEvent,
    GenerationRun,
    GenerationRunStatus,
)
from episodic.canonical.storage import SqlAlchemyUnitOfWork
from tests.canonical_storage._generation_run_lease_support import (
    EXPIRED_LEASE,
    FUTURE_LEASE,
    LEASE_ERROR_CATEGORY,
    LEASE_ERROR_MESSAGE,
    checkpoint_for,
    claim_run,
    create_runs,
    end_run,
    reclaim,
)
from tests.canonical_storage._generation_run_support import NOW, make_generation_run

if typ.TYPE_CHECKING:
    import datetime as dt

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@dc.dataclass(frozen=True, slots=True)
class Case:
    """One kind of run in the partition, with its expected outcome.

    Attributes
    ----------
    status : GenerationRunStatus
        Lifecycle state the run is in when reclamation runs.
    lease_expires_at : dt.datetime | None
        Lease the run holds, or ``None`` when it holds none.
    open_checkpoint : bool
        Whether a ``created`` checkpoint is attached to the run.
    reclaimed : bool
        Whether the call must reclaim the run.
    """

    status: GenerationRunStatus
    lease_expires_at: dt.datetime | None
    open_checkpoint: bool
    reclaimed: bool


# One row per kind of run the primitive must tell apart. The reclaimed kind is
# present, and so is each non-reclaimed kind, which is what makes the exact-set
# assertion below non-vacuous in both directions.
PARTITION = {
    "pending": Case(
        GenerationRunStatus.PENDING,
        None,
        open_checkpoint=False,
        reclaimed=False,
    ),
    "running-no-lease": Case(
        GenerationRunStatus.RUNNING,
        None,
        open_checkpoint=False,
        reclaimed=False,
    ),
    "running-future-lease": Case(
        GenerationRunStatus.RUNNING,
        FUTURE_LEASE,
        open_checkpoint=False,
        reclaimed=False,
    ),
    "running-expired-open-checkpoint": Case(
        GenerationRunStatus.RUNNING,
        EXPIRED_LEASE,
        open_checkpoint=True,
        reclaimed=False,
    ),
    "running-expired-lease": Case(
        GenerationRunStatus.RUNNING,
        EXPIRED_LEASE,
        open_checkpoint=False,
        reclaimed=True,
    ),
    # Boundary: a lease expiring exactly at `now` has expired "at or before".
    "running-lease-expires-at-now": Case(
        GenerationRunStatus.RUNNING,
        NOW,
        open_checkpoint=False,
        reclaimed=True,
    ),
    "succeeded": Case(
        GenerationRunStatus.SUCCEEDED,
        EXPIRED_LEASE,
        open_checkpoint=False,
        reclaimed=False,
    ),
    "failed": Case(
        GenerationRunStatus.FAILED,
        EXPIRED_LEASE,
        open_checkpoint=False,
        reclaimed=False,
    ),
    "cancelled": Case(
        GenerationRunStatus.CANCELLED,
        EXPIRED_LEASE,
        open_checkpoint=False,
        reclaimed=False,
    ),
}


async def _seed_partition(
    session_factory: async_sessionmaker[AsyncSession],
) -> dict[str, GenerationRun]:
    """Commit one run per partition row and return them by row name."""
    runs = {name: make_generation_run() for name in PARTITION}
    await create_runs(session_factory, list(runs.values()))
    for name, case in PARTITION.items():
        run = runs[name]
        if case.status is not GenerationRunStatus.PENDING:
            # Claiming is what moves a run to `running`; the lease it carries
            # is a separate value, so a null-lease running run is claimable.
            await claim_run(
                session_factory,
                run.id,
                lease_expires_at=case.lease_expires_at,
            )
        if case.status.is_terminal():
            await end_run(session_factory, run.id, case.status)
        if case.open_checkpoint:
            async with SqlAlchemyUnitOfWork(session_factory) as uow:
                await uow.generation_runs.create_checkpoint(
                    checkpoint_for(run.id),
                )
                await uow.commit()
    return runs


@pytest.mark.asyncio
async def test_reclamation_selects_exactly_the_expired_lease_state(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Only a running run with an expired lease and no open checkpoint moves."""
    seeded = await _seed_partition(session_factory)
    expected = {seeded[name].id for name, case in PARTITION.items() if case.reclaimed}
    assert expected, "the partition must contain at least one reclaimed run"
    assert len(expected) < len(PARTITION), "the partition must contain refusals"

    reclaimed = await reclaim(session_factory)

    assert {run.id for run in reclaimed} == expected, [
        (run.id, run.status) for run in reclaimed
    ]
    await _assert_partition_state(session_factory, seeded)


async def _assert_partition_state(
    session_factory: async_sessionmaker[AsyncSession],
    seeded: dict[str, GenerationRun],
) -> None:
    """Assert each seeded run's persisted state matches its partition row."""
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        observed = {
            name: await uow.generation_runs.get_run(run.id)
            for name, run in seeded.items()
        }
        events = {
            name: await uow.generation_runs.list_events(run.id)
            for name, run in seeded.items()
        }
    for name, case in PARTITION.items():
        run = observed[name]
        assert run is not None, f"{name}: run was not persisted"
        expected_status = GenerationRunStatus.FAILED if case.reclaimed else case.status
        assert run.status is expected_status, f"{name}: {run.status}"
        if case.reclaimed:
            _assert_reclaimed(name, run, events[name])
        else:
            assert events[name] == (), f"{name}: appended {events[name]!r}"


def _assert_reclaimed(
    name: str,
    run: GenerationRun,
    events: tuple[GenerationEvent, ...],
) -> None:
    """Assert one reclaimed run's event, error fields, and end time."""
    kinds = [event.kind for event in events]
    payloads = [event.payload for event in events]
    assert kinds == ["run.failed"], f"{name}: events {kinds!r}"
    assert payloads[0] == {
        "error_category": LEASE_ERROR_CATEGORY,
        "error_message": LEASE_ERROR_MESSAGE,
    }, f"{name}: payload {payloads[0]!r}"
    assert run.error_category == LEASE_ERROR_CATEGORY, f"{name}: {run.error_category}"
    assert run.error_message == LEASE_ERROR_MESSAGE, f"{name}: {run.error_message}"
    assert run.current_node is None, f"{name}: node {run.current_node!r}"
    assert run.ended_at == NOW, f"{name}: ended_at {run.ended_at!r}"


@pytest.mark.asyncio
async def test_reclamation_rejects_non_positive_limit(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A non-positive limit is a caller error, not a silent empty batch."""
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        with pytest.raises(ValueError, match="limit must be a positive integer"):
            await uow.generation_runs.fail_expired_leases(now=NOW, limit=0)
