"""Generated invariants for the expired-lease batch slice.

``test_generation_run_lease_reclamation.py`` pins *which* runs are eligible as
a finite state partition, and ``test_generation_run_lease_transitions.py``
pins one handwritten ordered backlog. Neither generalizes the batch contract:
that a call returns the leading ``(lease_expires_at, id)`` slice of the
eligible runs, that repeated calls drain the backlog without repeating or
skipping a run, and that the call after the backlog empties reclaims nothing.

The backlogs here are small because every example persists real rows. A narrow
lease range is deliberate: it makes expiry ties common, so the identifier
tiebreak is exercised rather than assumed.
"""

import datetime as dt
import typing as typ

import hypothesis.strategies as st
import pytest
from hypothesis import HealthCheck, event, given, settings

from tests.canonical_storage._generation_run_lease_support import (
    claim_run,
    create_runs,
    reclaim,
)
from tests.canonical_storage._generation_run_support import NOW, make_generation_run

if typ.TYPE_CHECKING:
    import uuid

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    type SessionFactory = async_sessionmaker[AsyncSession]
else:
    type SessionFactory = object


async def _seed_expired_backlog(
    factory: SessionFactory,
    offsets: list[int],
) -> tuple[list[uuid.UUID], dict[uuid.UUID, dt.datetime]]:
    """Commit one expired run per offset and return their expected order."""
    runs = [make_generation_run() for _ in offsets]
    await create_runs(factory, runs)
    leases: dict[uuid.UUID, dt.datetime] = {}
    for run, offset in zip(runs, offsets, strict=True):
        # Offsets are minutes before ``NOW`` and repeat across small draws,
        # which is what produces the ties the ordering assertion needs.
        lease = NOW - dt.timedelta(minutes=offset + 1)
        await claim_run(factory, run.id, lease_expires_at=lease)
        leases[run.id] = lease
    ordered = sorted((leases[run.id], run.id) for run in runs)
    return [run_id for _, run_id in ordered], leases


@given(
    offsets=st.lists(
        st.integers(min_value=0, max_value=5),
        min_size=1,
        max_size=6,
    ),
    limit=st.integers(min_value=1, max_value=6),
)
@settings(
    max_examples=12,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@pytest.mark.asyncio
async def test_reclamation_drains_the_backlog_one_ordered_slice_at_a_time(
    session_factory: SessionFactory,
    offsets: list[int],
    limit: int,
) -> None:
    """Repeated calls yield the eligible runs in order, exactly once each."""
    factory = session_factory
    event(f"backlog_size={len(offsets)}")
    event(f"tied_leases={len(offsets) - len(set(offsets))}")
    expected, _ = await _seed_expired_backlog(factory, offsets)

    collected: list[uuid.UUID] = []
    while len(collected) < len(expected):
        batch = [run.id for run in await reclaim(factory, limit=limit)]
        assert batch, "a non-empty backlog yielded no work"
        assert batch == expected[len(collected) :][:limit], (
            f"batch {batch} is not the next {limit} of {expected}"
        )
        collected.extend(batch)

    assert collected == expected, "a run was reclaimed twice or out of order"
    assert await reclaim(factory, limit=limit) == (), (
        "a drained backlog reclaimed again"
    )
