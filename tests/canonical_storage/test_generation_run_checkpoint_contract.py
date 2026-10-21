"""Drive the shared checkpoint scenarios against the SQLAlchemy composite.

The scenarios live in ``tests/generation_run_contract_scenarios.py`` and are
also driven against the in-memory adapter by
``tests/test_generation_checkpoint_port_contract.py``. This module adds the
PostgreSQL driver and the hooks that expose committed state, so that both
implementations are held to one definition of the checkpoint contract rather
than two hand-maintained suites that can drift apart.

Each scenario costs one ``py-pglite`` fixture setup, so only the checkpoint
scenarios are driven here; the run- and event-level contracts remain covered by
``test_generation_runs.py``, ``test_generation_run_claims.py``, and
``test_generation_run_terminal_claims.py``.

The scenarios assert on *committed* state, which here is also a mechanical
constraint. ``py-pglite`` serves a single WebAssembly PostgreSQL backend, so the
fresh read cannot take a connection while the scenario's unit of work still
holds one. The hooks therefore commit the scenario's unit of work before they
read, which is the "commit-plus-new-unit-of-work" shape the plan specifies.
"""

import dataclasses as dc
import typing as typ

import pytest
import pytest_asyncio
import sqlalchemy as sa

from episodic.canonical.storage import SqlAlchemyUnitOfWork
from tests import generation_run_checkpoint_listing_scenarios as listing
from tests import generation_run_contract_scenarios as scenarios
from tests.canonical_storage._generation_run_support import (
    persist_generation_run_prerequisites,
)

if typ.TYPE_CHECKING:
    import collections.abc as cabc
    import uuid

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from episodic.canonical.domain import Checkpoint, GenerationRun
    from episodic.canonical.generation_run_ports import GenerationRunPort


@dc.dataclass(frozen=True, slots=True)
class SqlScenarioHooks:
    """The three backend-specific hooks the shared scenarios call."""

    prepare_run: cabc.Callable[[GenerationRun], cabc.Awaitable[None]]
    read_fresh: cabc.Callable[[uuid.UUID], cabc.Awaitable[Checkpoint | None]]
    count_checkpoints: cabc.Callable[[uuid.UUID], cabc.Awaitable[int]]


@pytest_asyncio.fixture
async def scenario_uow(
    session_factory: async_sessionmaker[AsyncSession],
) -> cabc.AsyncIterator[SqlAlchemyUnitOfWork]:
    """Yield the one unit of work every SQL scenario writes through.

    ``store`` and ``hooks`` both derive from this fixture, so the port a
    scenario writes through and the commit its later read performs belong to the
    same transaction. Nothing else observes the scenario's work in between.

    Yields
    ------
    SqlAlchemyUnitOfWork
        The open unit of work the scenario's port is bound to, closed when the
        test ends.
    """
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        yield uow


@pytest.fixture
def hooks(
    scenario_uow: SqlAlchemyUnitOfWork,
    session_factory: async_sessionmaker[AsyncSession],
) -> SqlScenarioHooks:
    """Build PostgreSQL hooks that observe only committed state."""

    async def prepare_run(run: GenerationRun) -> None:
        """Commit the series, episode, and job the run's foreign keys need."""
        await persist_generation_run_prerequisites(session_factory, run)

    async def read_fresh(checkpoint_id: uuid.UUID) -> Checkpoint | None:
        """Commit the scenario's work, then read it back through a new one."""
        await scenario_uow.commit()
        async with SqlAlchemyUnitOfWork(session_factory) as uow:
            return await uow.generation_runs.get_checkpoint(checkpoint_id)

    async def count_checkpoints(checkpoint_id: uuid.UUID) -> int:
        """Count committed rows for one checkpoint identifier.

        The scenario's unit of work is committed first. Without that commit a
        row an adapter wrote before raising would be invisible here, and the
        "no row may be written" assertion would hold for the wrong reason.

        Raw SQL rather than the ORM record, so the hook stays usable while the
        record type is still being introduced.

        Returns
        -------
        int
            Number of committed rows holding this identifier.
        """
        await scenario_uow.commit()
        statement = sa.text(
            "SELECT count(*) FROM review_checkpoints WHERE id = :checkpoint_id"
        )
        async with session_factory() as session:
            result = await session.execute(
                statement,
                {"checkpoint_id": checkpoint_id},
            )
            return result.scalar_one()

    return SqlScenarioHooks(
        prepare_run=prepare_run,
        read_fresh=read_fresh,
        count_checkpoints=count_checkpoints,
    )


@pytest.fixture
def store(scenario_uow: SqlAlchemyUnitOfWork) -> GenerationRunPort:
    """Return the composite port bound to the scenario's unit of work."""
    return scenario_uow.generation_runs


@pytest.mark.asyncio
async def test_store_satisfies_generation_run_port(store: GenerationRunPort) -> None:
    """The SQLAlchemy composite satisfies the composite port."""
    await scenarios.scenario_store_satisfies_generation_run_port(store)


@pytest.mark.asyncio
async def test_creation_persists_checkpoint(
    store: GenerationRunPort,
    hooks: SqlScenarioHooks,
) -> None:
    """A created checkpoint survives into a later unit of work."""
    await scenarios.scenario_creation_persists_checkpoint(
        store,
        prepare_run=hooks.prepare_run,
        read_fresh=hooks.read_fresh,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "transition",
    scenarios.TRANSITIONS,
    ids=scenarios.TRANSITION_IDS,
)
async def test_transition_persists_domain_result(
    store: GenerationRunPort,
    hooks: SqlScenarioHooks,
    transition: scenarios.Transition,
) -> None:
    """Each SQL transition persists exactly what the domain returned."""
    await scenarios.scenario_transition_persists_domain_result(
        store,
        prepare_run=hooks.prepare_run,
        read_fresh=hooks.read_fresh,
        transition=transition,
    )


@pytest.mark.asyncio
async def test_response_round_trips_payload(
    store: GenerationRunPort,
    hooks: SqlScenarioHooks,
) -> None:
    """The reviewer payload round-trips through JSONB without loss."""
    await scenarios.scenario_response_round_trips_payload(
        store,
        prepare_run=hooks.prepare_run,
        read_fresh=hooks.read_fresh,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case",
    scenarios.TERMINAL_CASES,
    ids=scenarios.TERMINAL_CASE_IDS,
)
async def test_terminal_checkpoint_rejects_transition(
    store: GenerationRunPort,
    hooks: SqlScenarioHooks,
    case: scenarios.TerminalCase,
) -> None:
    """The compare-and-set predicate rejects all nine terminal combos."""
    await scenarios.scenario_terminal_checkpoint_rejects_transition(
        store,
        prepare_run=hooks.prepare_run,
        read_fresh=hooks.read_fresh,
        case=case,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "transition",
    scenarios.TRANSITIONS,
    ids=scenarios.TRANSITION_IDS,
)
async def test_transition_rejects_unknown_checkpoint(
    store: GenerationRunPort,
    hooks: SqlScenarioHooks,
    transition: scenarios.Transition,
) -> None:
    """Each transition raises the domain not-found error."""
    await scenarios.scenario_transition_rejects_unknown_checkpoint(
        store,
        prepare_run=hooks.prepare_run,
        transition=transition,
    )


@pytest.mark.asyncio
async def test_creation_rejects_unknown_run(
    store: GenerationRunPort,
    hooks: SqlScenarioHooks,
) -> None:
    """Creating against a missing run fails and commits no row."""
    await scenarios.scenario_creation_rejects_unknown_run(
        store,
        prepare_run=hooks.prepare_run,
        count_checkpoints=hooks.count_checkpoints,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("status", scenarios.TERMINAL_STATUSES, ids=str)
async def test_creation_rejects_terminal_status(
    store: GenerationRunPort,
    hooks: SqlScenarioHooks,
    status: scenarios.CheckpointStatus,
) -> None:
    """Creating a checkpoint in a terminal state is refused."""
    await scenarios.scenario_creation_rejects_terminal_status(
        store,
        prepare_run=hooks.prepare_run,
        status=status,
    )


@pytest.mark.asyncio
async def test_creation_rejects_duplicate_identifier(
    store: GenerationRunPort,
    hooks: SqlScenarioHooks,
) -> None:
    """A duplicate identifier is translated to the domain conflict."""
    await scenarios.scenario_creation_rejects_duplicate_identifier(
        store,
        prepare_run=hooks.prepare_run,
        read_fresh=hooks.read_fresh,
    )


@pytest.mark.asyncio
async def test_listing_returns_checkpoints_oldest_created_first(
    store: GenerationRunPort,
    hooks: SqlScenarioHooks,
) -> None:
    """The SQL listing orders checkpoints by ``(created_at, id)``."""
    await listing.scenario_listing_returns_checkpoints_oldest_created_first(
        store,
        prepare_run=hooks.prepare_run,
    )


@pytest.mark.asyncio
async def test_listing_filters_by_status(
    store: GenerationRunPort,
    hooks: SqlScenarioHooks,
) -> None:
    """The SQL listing's status filter selects only matching checkpoints."""
    await listing.scenario_listing_filters_by_status(
        store,
        prepare_run=hooks.prepare_run,
    )


@pytest.mark.asyncio
async def test_listing_applies_bounds_within_a_status_filter(
    store: GenerationRunPort,
    hooks: SqlScenarioHooks,
) -> None:
    """The SQL listing paginates the filtered result, not the stored rows."""
    await listing.scenario_listing_applies_bounds_within_a_status_filter(
        store,
        prepare_run=hooks.prepare_run,
    )


@pytest.mark.asyncio
async def test_listing_rejects_unknown_run(
    store: GenerationRunPort,
    hooks: SqlScenarioHooks,
) -> None:
    """Listing for a run that was never stored raises ``RunNotFound``."""
    await listing.scenario_listing_rejects_unknown_run(
        store,
        prepare_run=hooks.prepare_run,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("limit", "offset"),
    listing.NEGATIVE_BOUND_CASES,
    ids=["negative-limit", "negative-offset"],
)
async def test_listing_rejects_negative_bounds(
    store: GenerationRunPort,
    hooks: SqlScenarioHooks,
    limit: int,
    offset: int,
) -> None:
    """A negative ``limit`` or ``offset`` is refused, not clamped."""
    await listing.scenario_listing_rejects_negative_bounds(
        store,
        prepare_run=hooks.prepare_run,
        limit=limit,
        offset=offset,
    )
