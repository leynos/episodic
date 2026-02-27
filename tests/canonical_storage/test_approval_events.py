"""Unit tests for canonical storage approval event repositories.

Examples
--------
Run the approval event repository tests:

>>> pytest tests/canonical_storage/test_approval_events.py
"""

from __future__ import annotations

import datetime as dt
import typing as typ
import uuid

import pytest
from sqlalchemy import exc as sa_exc

from episodic.canonical.domain import ApprovalEvent, ApprovalState
from episodic.canonical.storage import SqlAlchemyUnitOfWork

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@pytest.mark.asyncio
async def test_approval_event_fk_constraint(session_factory: object) -> None:
    """Approval event foreign key rejects non-existent episode."""
    now = dt.datetime.now(dt.UTC)
    factory = typ.cast("async_sessionmaker[AsyncSession]", session_factory)

    async with SqlAlchemyUnitOfWork(factory) as uow:
        event = ApprovalEvent(
            id=uuid.uuid4(),
            episode_id=uuid.uuid4(),
            actor="test@example.com",
            from_state=None,
            to_state=ApprovalState.DRAFT,
            note="Orphan event.",
            payload={},
            created_at=now,
        )
        await uow.approval_events.add(event)
        with pytest.raises(
            sa_exc.IntegrityError,
            match=r"foreign key|FOREIGN KEY|fk|violates",
        ):
            await uow.commit()


@pytest.mark.asyncio
async def test_list_for_episode_returns_empty_for_unknown(
    session_factory: object,
) -> None:
    """Listing approval events for a non-existent episode returns empty."""
    factory = typ.cast("async_sessionmaker[AsyncSession]", session_factory)
    async with SqlAlchemyUnitOfWork(factory) as uow:
        events = await uow.approval_events.list_for_episode(uuid.uuid4())

    assert events == [], "Expected an empty list for a missing episode."
