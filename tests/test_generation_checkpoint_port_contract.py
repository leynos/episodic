"""Contract tests for generation checkpoint port implementations.

The scenarios themselves live in
``tests/generation_run_contract_scenarios.py`` and are driven against every
adapter. This module supplies the in-memory driver and the hooks that make an
in-process mapping behave like a committed store.
"""

import typing as typ

import pytest

from episodic.canonical.adapters.generation_runs import InMemoryGenerationRunStore
from tests import generation_run_checkpoint_listing_scenarios as listing
from tests import generation_run_contract_scenarios as scenarios

if typ.TYPE_CHECKING:
    import uuid

    from episodic.canonical.domain import Checkpoint, CheckpointStatus
    from episodic.canonical.generation_run_ports import GenerationRunPort
    from tests.generation_run_contract_scenarios import (
        CountCheckpoints,
        PrepareRun,
        ReadFresh,
    )

pytestmark = [pytest.mark.asyncio]


@pytest.fixture
def store() -> GenerationRunPort:
    """Create a deterministic in-memory store for each contract test."""
    return InMemoryGenerationRunStore(time_provider=lambda: scenarios.NOW)


@pytest.fixture
def prepare_run() -> PrepareRun:
    """Return the in-memory no-op prerequisite hook."""

    async def _prepare(_run: object) -> None:
        """Do nothing: the in-memory store enforces no foreign keys."""

    return _prepare


@pytest.fixture
def read_fresh(store: GenerationRunPort) -> ReadFresh:
    """Return a hook that reads a checkpoint back from the same mapping."""

    async def _read(checkpoint_id: uuid.UUID) -> Checkpoint | None:
        """Return the stored checkpoint, already visible to readers."""
        return await store.get_checkpoint(checkpoint_id)

    return _read


@pytest.fixture
def count_checkpoints(store: GenerationRunPort) -> CountCheckpoints:
    """Return a hook counting stored checkpoints by identifier."""

    async def _count(checkpoint_id: uuid.UUID) -> int:
        """Report whether the identifier is present in the mapping."""
        return int(await store.get_checkpoint(checkpoint_id) is not None)

    return _count


async def test_store_satisfies_generation_run_port(store: GenerationRunPort) -> None:
    """The in-memory adapter satisfies the composite port."""
    await scenarios.scenario_store_satisfies_generation_run_port(store)


async def test_creation_persists_checkpoint(
    store: GenerationRunPort,
    prepare_run: PrepareRun,
    read_fresh: ReadFresh,
) -> None:
    """A created checkpoint is readable and keeps its option order."""
    await scenarios.scenario_creation_persists_checkpoint(
        store,
        prepare_run=prepare_run,
        read_fresh=read_fresh,
    )


@pytest.mark.parametrize(
    "transition",
    scenarios.TRANSITIONS,
    ids=scenarios.TRANSITION_IDS,
)
async def test_transition_persists_domain_result(
    store: GenerationRunPort,
    prepare_run: PrepareRun,
    read_fresh: ReadFresh,
    transition: scenarios.Transition,
) -> None:
    """Each transition persists the entity the domain returned."""
    await scenarios.scenario_transition_persists_domain_result(
        store,
        prepare_run=prepare_run,
        read_fresh=read_fresh,
        transition=transition,
    )


async def test_response_round_trips_payload(
    store: GenerationRunPort,
    prepare_run: PrepareRun,
    read_fresh: ReadFresh,
) -> None:
    """A reviewer response round-trips action, identity, and payload."""
    await scenarios.scenario_response_round_trips_payload(
        store,
        prepare_run=prepare_run,
        read_fresh=read_fresh,
    )


@pytest.mark.parametrize(
    "case",
    scenarios.TERMINAL_CASES,
    ids=scenarios.TERMINAL_CASE_IDS,
)
async def test_terminal_checkpoint_rejects_transition(
    store: GenerationRunPort,
    prepare_run: PrepareRun,
    read_fresh: ReadFresh,
    case: scenarios.TerminalCase,
) -> None:
    """A terminal checkpoint rejects all nine further transitions."""
    await scenarios.scenario_terminal_checkpoint_rejects_transition(
        store,
        prepare_run=prepare_run,
        read_fresh=read_fresh,
        case=case,
    )


@pytest.mark.parametrize(
    "transition",
    scenarios.TRANSITIONS,
    ids=scenarios.TRANSITION_IDS,
)
async def test_transition_rejects_unknown_checkpoint(
    store: GenerationRunPort,
    prepare_run: PrepareRun,
    transition: scenarios.Transition,
) -> None:
    """Each transition refuses an identifier that was never stored."""
    await scenarios.scenario_transition_rejects_unknown_checkpoint(
        store,
        prepare_run=prepare_run,
        transition=transition,
    )


async def test_creation_rejects_unknown_run(
    store: GenerationRunPort,
    prepare_run: PrepareRun,
    count_checkpoints: CountCheckpoints,
) -> None:
    """Creating against a missing run fails and writes nothing."""
    await scenarios.scenario_creation_rejects_unknown_run(
        store,
        prepare_run=prepare_run,
        count_checkpoints=count_checkpoints,
    )


@pytest.mark.parametrize("status", scenarios.TERMINAL_STATUSES, ids=str)
async def test_creation_rejects_terminal_status(
    store: GenerationRunPort,
    prepare_run: PrepareRun,
    status: CheckpointStatus,
) -> None:
    """Creating a checkpoint in a terminal state is refused."""
    await scenarios.scenario_creation_rejects_terminal_status(
        store,
        prepare_run=prepare_run,
        status=status,
    )


async def test_creation_rejects_duplicate_identifier(
    store: GenerationRunPort,
    prepare_run: PrepareRun,
    read_fresh: ReadFresh,
) -> None:
    """A duplicate identifier must not overwrite the stored checkpoint."""
    await scenarios.scenario_creation_rejects_duplicate_identifier(
        store,
        prepare_run=prepare_run,
        read_fresh=read_fresh,
    )


async def test_listing_returns_checkpoints_oldest_created_first(
    store: GenerationRunPort,
    prepare_run: PrepareRun,
) -> None:
    """The listing orders checkpoints by ``(created_at, id)``."""
    await listing.scenario_listing_returns_checkpoints_oldest_created_first(
        store,
        prepare_run=prepare_run,
    )


async def test_listing_filters_by_status(
    store: GenerationRunPort,
    prepare_run: PrepareRun,
) -> None:
    """The listing's status filter selects only matching checkpoints."""
    await listing.scenario_listing_filters_by_status(
        store,
        prepare_run=prepare_run,
    )


async def test_listing_applies_bounds_within_a_status_filter(
    store: GenerationRunPort,
    prepare_run: PrepareRun,
) -> None:
    """The listing paginates the filtered result, not the stored rows."""
    await listing.scenario_listing_applies_bounds_within_a_status_filter(
        store,
        prepare_run=prepare_run,
    )


async def test_listing_rejects_unknown_run(
    store: GenerationRunPort,
    prepare_run: PrepareRun,
) -> None:
    """Listing for a run that was never stored raises ``RunNotFound``."""
    await listing.scenario_listing_rejects_unknown_run(
        store,
        prepare_run=prepare_run,
    )


@pytest.mark.parametrize(
    ("limit", "offset"),
    listing.NEGATIVE_BOUND_CASES,
    ids=["negative-limit", "negative-offset"],
)
async def test_listing_rejects_negative_bounds(
    store: GenerationRunPort,
    prepare_run: PrepareRun,
    limit: int,
    offset: int,
) -> None:
    """A negative ``limit`` or ``offset`` is refused, not clamped."""
    await listing.scenario_listing_rejects_negative_bounds(
        store,
        prepare_run=prepare_run,
        limit=limit,
        offset=offset,
    )
