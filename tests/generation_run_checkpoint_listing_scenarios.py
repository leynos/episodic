"""Shared behavioural contracts for listing generation-run checkpoints.

``list_checkpoints`` is the one port method with two independent
implementations and, before this module, no scenario driving either of them.
An unpinned pair of implementations is a divergence that reads as
interchangeable -- the blind spot that INV-CKPT-1 exists to close for the
transition methods -- so every case below is driven against both adapters and
the value the two must agree on is asserted exactly.

Each scenario is a plain coroutine rather than a method on a ``Test``-prefixed
class, for the reason EP-M3 records for the sibling scenario module: a class in
a module pytest does not collect is still collected once the module is imported
into a collected one, under the *importer's* namespace, so a shared base class
would run its fixtures in the wrong context. Functions have no such trap, and
this module is deliberately named so pytest does not collect it directly.
"""

import dataclasses as dc
import datetime as dt
import typing as typ
import uuid

import pytest

from episodic.canonical.domain import CheckpointStatus
from episodic.canonical.generation_run_errors import RunNotFound
from tests.generation_run_contract_scenarios import (
    NOW,
    make_checkpoint,
    make_run,
    respond,
)

if typ.TYPE_CHECKING:
    from episodic.canonical.domain import Checkpoint
    from episodic.canonical.generation_run_ports import GenerationRunPort
    from tests.generation_run_contract_scenarios import PrepareRun

#: One step between the instants the scenarios record, so a checkpoint's
#: position in the expected order is decided by a value written here rather
#: than by how long a call took.
STEP = dt.timedelta(minutes=1)

#: Identifiers for the same-instant pair. They are chosen rather than generated
#: so the expected order of two checkpoints sharing one ``created_at`` is a
#: literal in the scenario instead of a re-run of the sort under test.
TIE_LOW_ID = uuid.UUID(int=1)
TIE_HIGH_ID = uuid.UUID(int=2)

#: Each case is a ``(limit, offset)`` pair naming a bound the port rejects.
NEGATIVE_BOUND_CASES = ((-1, 0), (0, -1))


def _checkpoint_at(
    run_id: uuid.UUID,
    created_at: dt.datetime,
    *,
    checkpoint_id: uuid.UUID | None = None,
) -> Checkpoint:
    """Build a created checkpoint recorded at a chosen instant."""
    return dc.replace(
        make_checkpoint(run_id, checkpoint_id=checkpoint_id),
        created_at=created_at,
    )


async def _create_run(store: GenerationRunPort, prepare_run: PrepareRun) -> uuid.UUID:
    """Persist a run's prerequisites and the run itself, returning its id."""
    run = make_run()
    await prepare_run(run)
    await store.create_run(run)
    return run.id


async def scenario_listing_returns_checkpoints_oldest_created_first(
    store: GenerationRunPort,
    *,
    prepare_run: PrepareRun,
) -> None:
    """Return a run's checkpoints in ``(created_at, id)`` order.

    The checkpoints are created in an order that differs from the expected one,
    so a listing that returned rows in insertion order, or in whatever order
    the storage engine happened to hand back, fails rather than passes by
    luck. The last two share an instant, which pins the ``id`` half of the sort
    key on its own.
    """
    run_id = await _create_run(store, prepare_run)
    newest = _checkpoint_at(run_id, NOW + 2 * STEP)
    tie_high = _checkpoint_at(run_id, NOW + STEP, checkpoint_id=TIE_HIGH_ID)
    tie_low = _checkpoint_at(run_id, NOW + STEP, checkpoint_id=TIE_LOW_ID)
    oldest = _checkpoint_at(run_id, NOW)
    for checkpoint in (newest, tie_high, tie_low, oldest):
        await store.create_checkpoint(checkpoint)

    listed = await store.list_checkpoints(run_id)

    assert [checkpoint.id for checkpoint in listed] == [
        oldest.id,
        tie_low.id,
        tie_high.id,
        newest.id,
    ], f"listing order: {[checkpoint.id for checkpoint in listed]!r}"


async def scenario_listing_filters_by_status(
    store: GenerationRunPort,
    *,
    prepare_run: PrepareRun,
) -> None:
    """Return only the checkpoints whose status matches the filter.

    The unfiltered case is asserted first: a filter that selected nothing at
    all would otherwise satisfy every status expectation below vacuously.
    """
    run_id = await _create_run(store, prepare_run)
    early = await store.create_checkpoint(_checkpoint_at(run_id, NOW))
    answered = await store.create_checkpoint(_checkpoint_at(run_id, NOW + STEP))
    late = await store.create_checkpoint(_checkpoint_at(run_id, NOW + 2 * STEP))
    resolved = await respond(store, answered.id)

    unfiltered = await store.list_checkpoints(run_id)
    created = await store.list_checkpoints(
        run_id,
        status=CheckpointStatus.CREATED,
    )
    responded = await store.list_checkpoints(
        run_id,
        status=CheckpointStatus.RESPONDED,
    )
    timed_out = await store.list_checkpoints(
        run_id,
        status=CheckpointStatus.TIMED_OUT,
    )

    assert [checkpoint.id for checkpoint in unfiltered] == [
        early.id,
        answered.id,
        late.id,
    ], "the unfiltered listing must see every checkpoint"
    assert [checkpoint.id for checkpoint in created] == [early.id, late.id], (
        f"created filter: {[checkpoint.id for checkpoint in created]!r}"
    )
    assert [checkpoint.id for checkpoint in responded] == [resolved.id], (
        f"responded filter: {[checkpoint.id for checkpoint in responded]!r}"
    )
    assert timed_out == (), "a status no checkpoint reached must select nothing"


async def scenario_listing_applies_bounds_within_a_status_filter(
    store: GenerationRunPort,
    *,
    prepare_run: PrepareRun,
) -> None:
    """Apply ``limit`` and ``offset`` to the filtered result, not to the table.

    The first checkpoint is responded to, so ``offset=1`` crosses a row the
    filter excludes. An adapter that paginated before filtering would return
    the wrong row here rather than merely the wrong count.
    """
    run_id = await _create_run(store, prepare_run)
    checkpoints = [
        await store.create_checkpoint(_checkpoint_at(run_id, NOW + index * STEP))
        for index in range(4)
    ]
    await respond(store, checkpoints[0].id)
    surviving = [checkpoint.id for checkpoint in checkpoints[1:]]

    filtered = await store.list_checkpoints(
        run_id,
        status=CheckpointStatus.CREATED,
    )
    page = await store.list_checkpoints(
        run_id,
        status=CheckpointStatus.CREATED,
        limit=1,
        offset=1,
    )

    assert [checkpoint.id for checkpoint in filtered] == surviving, (
        f"filtered listing: {[checkpoint.id for checkpoint in filtered]!r}"
    )
    assert [checkpoint.id for checkpoint in page] == [surviving[1]], (
        f"second filtered row: {[checkpoint.id for checkpoint in page]!r}"
    )


async def scenario_listing_rejects_unknown_run(
    store: GenerationRunPort,
    *,
    prepare_run: PrepareRun,
) -> None:
    """Refuse to list checkpoints for a run that was never stored.

    The run's prerequisites are committed first, so the refusal cannot be an
    accident of a foreign key or a missing parent: the run row itself is what
    the store cannot find.
    """
    run = make_run()
    await prepare_run(run)

    with pytest.raises(RunNotFound):
        await store.list_checkpoints(run.id)


async def scenario_listing_rejects_negative_bounds(
    store: GenerationRunPort,
    *,
    prepare_run: PrepareRun,
    limit: int,
    offset: int,
) -> None:
    """Refuse a negative bound rather than clamping it to zero.

    The run exists and holds no checkpoints, so an adapter that clamped the
    bound would return an empty tuple instead of raising, and the assertion
    would fail rather than pass on a missing run.
    """
    run_id = await _create_run(store, prepare_run)

    with pytest.raises(ValueError, match="non-negative"):
        await store.list_checkpoints(run_id, limit=limit, offset=offset)
