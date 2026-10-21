"""Identity-map safety for the SQL review-checkpoint store's lost races.

A compare-and-set that matches no row is the one path whose entire job is to
report what the database actually holds. The session, meanwhile, is holding a
copy of that row which is stale precisely because the writer that won was
external. Anything that answers from that copy instead of from PostgreSQL
reports a status no row ever had.

These tests drive one ``py-pglite`` fixture each, so they are kept apart from
the round-trip fidelity coverage in :mod:`test_review_checkpoints`.
"""

import datetime as dt
import typing as typ

import pytest
import sqlalchemy as sa

from episodic.canonical.domain import (
    CheckpointAction,
    CheckpointResponse,
    CheckpointStatus,
)
from episodic.canonical.generation_run_errors import CheckpointAlreadyTerminal
from episodic.canonical.storage import (
    SqlAlchemyReviewCheckpointStore,
    review_checkpoints,
)
from episodic.canonical.storage.review_checkpoint_models import ReviewCheckpointRecord
from tests.canonical_storage import _generation_run_support as support

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

NOW = dt.datetime(2026, 6, 24, 8, 30, tzinfo=dt.UTC)


@pytest.mark.asyncio
async def test_lost_race_reports_the_stored_status_not_the_rejected_write(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A refused compare-and-set must not leave the session asserting a lie.

    ``_raise_lost_race`` exists to answer what ``rowcount == 0`` cannot: did the
    row vanish, or had another writer already resolved it? Either answer needs
    the *stored* value, and reading it back through the session does not supply
    one. The session's copy reads ``created``, because a writer that does not
    route through the ORM leaves the copy untouched, and the copy is what a
    plain ``session.get`` answers from -- no round trip, and no hint that the
    row says ``timed_out``. A caller that catches the exception and reads the
    checkpoint back is told a reviewer answered a checkpoint that timed out.

    The identity map's entries are weak, so a stale instance survives only while
    some caller holds it -- and ``_resolve`` is exactly such a caller, binding
    the record at its own read and keeping it alive across the compare-and-set.
    The reference below stands in for that. Without it the entry is collected, a
    fresh query returns the truth, and the defect hides: the test would pass
    against the unfixed store, which is why it is pinned deliberately.

    The comparison is made against a raw ``SELECT`` of the row, so the two ORM
    reads below cannot agree on the same wrong answer.

    The row is resolved through a raw ``UPDATE`` rather than a second unit of
    work, because py-pglite serves one PostgreSQL backend: a concurrent session
    would block rather than race.
    """
    committed = await support.commit_run_and_checkpoint(session_factory)
    events: list[tuple[str, str, dict[str, object]]] = []

    def record_event(level: str, message: str, **fields: object) -> None:
        events.append((level, message, fields))

    monkeypatch.setattr(review_checkpoints, "_log_event", record_event)

    async with session_factory() as session:
        store = SqlAlchemyReviewCheckpointStore(session)
        # Hold the row's instance for the duration, as _resolve does: identity
        # map entries are weak, so an unheld copy is collected and re-read.
        pinned = await session.get(ReviewCheckpointRecord, committed.checkpoint_id)
        assert pinned is not None, "the committed checkpoint must be readable"
        assert pinned.status is CheckpointStatus.CREATED, (
            "the session must begin by holding the row as created"
        )
        # An external writer resolves the row without touching this session.
        await session.execute(
            sa
            .update(ReviewCheckpointRecord)
            .where(ReviewCheckpointRecord.id == committed.checkpoint_id)
            .values(
                status=CheckpointStatus.TIMED_OUT.value,
                resolved_at=NOW + dt.timedelta(minutes=5),
                responded_by="system",
            )
            .execution_options(synchronize_session=False)
        )

        with pytest.raises(CheckpointAlreadyTerminal):
            await store.respond_to_checkpoint(
                committed.checkpoint_id,
                response=CheckpointResponse(
                    action=CheckpointAction.APPROVE,
                    payload={"approved": True},
                    responded_at=NOW + dt.timedelta(minutes=1),
                    responded_by="reviewer@example.com",
                ),
            )

        # Anchored to the row itself, so the assertions below cannot be
        # satisfied by two ORM reads agreeing on the same wrong answer.
        stored = await session.scalar(
            sa.text("SELECT status FROM review_checkpoints WHERE id = :id"),
            {"id": committed.checkpoint_id},
        )
        assert stored == CheckpointStatus.TIMED_OUT.value, (
            f"the external writer's value must still be the stored one: {stored!r}"
        )

        reread = await store.get_checkpoint(committed.checkpoint_id)

        assert reread is not None, "the checkpoint must remain readable"
        assert reread.status is CheckpointStatus.TIMED_OUT, (
            "after the refused transition the session must report the stored "
            f"status, not the one it tried to write: {reread.status}"
        )

    assert [event[1] for event in events] == [
        "sql_review_checkpoint_store.respond_checkpoint_already_terminal"
    ], "the lost race must be reported as an already-terminal checkpoint"
    assert events[0][2]["status"] == CheckpointStatus.TIMED_OUT.value, (
        "the event must report the stored status, not the refused transition's"
    )
