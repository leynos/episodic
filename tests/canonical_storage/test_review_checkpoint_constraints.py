"""Database-enforced constraints on the review-checkpoint table.

``test_review_checkpoints.py`` covers round-trip fidelity through the adapter.
This module covers the rules the database itself enforces -- the JSON shape
guard, the responded-fields implication, and the ``RESTRICT`` foreign key --
plus the one value those constraints let through that the mapper must still
refuse. Each case asserts the specific constraint name, so a broadened or
renamed constraint is caught rather than silently satisfied by an unrelated
violation.
"""

import datetime as dt
import typing as typ

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from episodic.canonical.storage import SqlAlchemyUnitOfWork
from tests.canonical_storage import _generation_run_support as support

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

NOW = dt.datetime(2026, 6, 24, 8, 30, tzinfo=dt.UTC)


@pytest.mark.asyncio
async def test_options_must_be_a_json_array(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A scalar written into options is rejected by the CHECK constraint."""
    committed = await support.commit_run_and_checkpoint(session_factory)
    statement = sa.text(
        "UPDATE review_checkpoints SET options = '\"approve\"'::jsonb "
        "WHERE id = :checkpoint_id"
    )

    with pytest.raises(IntegrityError, match="ck_review_checkpoints_options_array"):
        async with session_factory() as session, session.begin():
            await session.execute(statement, {"checkpoint_id": committed.checkpoint_id})


@pytest.mark.asyncio
async def test_non_string_option_is_rejected_when_read_back(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A stored array holding a non-string surfaces as the documented TypeError.

    The CHECK constraint only requires an array of some length, so a value this
    shape can reach storage; the mapper refuses it rather than coercing it into
    a domain checkpoint that would describe an option no reviewer could choose.
    """
    committed = await support.commit_run_and_checkpoint(session_factory)
    async with session_factory() as session, session.begin():
        await session.execute(
            sa.text(
                "UPDATE review_checkpoints SET options = "
                "'[\"approve\", 1]'::jsonb WHERE id = :checkpoint_id"
            ),
            {"checkpoint_id": committed.checkpoint_id},
        )

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        with pytest.raises(TypeError, match="must hold only strings"):
            await uow.generation_runs.get_checkpoint(committed.checkpoint_id)


@pytest.mark.asyncio
async def test_responded_status_requires_its_response_fields(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A row marked responded without action, responder, and time is refused.

    The positive half follows the refusal, so the test shows the constraint
    separates the two encodings rather than rejecting the status outright.
    """
    committed = await support.commit_run_and_checkpoint(session_factory)
    complete = {
        "checkpoint_id": committed.checkpoint_id,
        "responded_by": "reviewer@example.com",
        "resolved_at": NOW,
    }

    with pytest.raises(IntegrityError, match="ck_review_checkpoints_responded_fields"):
        async with session_factory() as session, session.begin():
            await session.execute(
                sa.text(
                    "UPDATE review_checkpoints SET status = 'responded' "
                    "WHERE id = :checkpoint_id"
                ),
                complete,
            )

    async with session_factory() as session, session.begin():
        await session.execute(
            sa.text(
                "UPDATE review_checkpoints SET status = 'responded', "
                "response_action = 'approve', responded_by = :responded_by, "
                "resolved_at = :resolved_at WHERE id = :checkpoint_id"
            ),
            complete,
        )


@pytest.mark.asyncio
async def test_checkpoint_keeps_its_run_from_being_deleted(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Deleting the parent run is refused while its checkpoint exists.

    ``RESTRICT`` is the audit-trail guarantee ADR-018 promises; a ``CASCADE``
    would delete the reviewer's decision silently, so the database, not just
    the adapter, has to refuse.
    """
    committed = await support.commit_run_and_checkpoint(session_factory)

    with pytest.raises(
        IntegrityError, match="review_checkpoints_generation_run_id_fkey"
    ):
        async with session_factory() as session, session.begin():
            await session.execute(
                sa.text("DELETE FROM generation_runs WHERE id = :run_id"),
                {"run_id": committed.run_id},
            )
