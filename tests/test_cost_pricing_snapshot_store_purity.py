"""Command/query separation for the pricing-snapshot store.

The store must not acquire side effects beyond the one row it is asked to
write. A read must leave unrelated pending work pending, a reuse must leave the
existing row untouched, and a new row must take its identifier from the
injected factory rather than reaching for a global.
"""

import datetime as dt
import typing as typ
import uuid

import pytest
import sqlalchemy as sa

from episodic.cost import (
    EnsuredPricingSnapshot,
    PricingSnapshotId,
    PricingSnapshotNotFoundError,
    SnapshotEnsureOutcome,
)
from episodic.cost.storage import (
    PricingSnapshotRecord,
    SqlAlchemyPricingSnapshotStore,
)
from tests.fixtures.cost import v1_pricing_snapshot

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    type SessionFactory = async_sessionmaker[AsyncSession]
else:  # pragma: no cover - runtime alias for evaluated test annotations.
    type SessionFactory = object

_PENDING_ID = uuid.UUID(int=501)


def _pending_record(content_hash: str) -> PricingSnapshotRecord:
    """Build a valid row that the session stages but does not flush."""
    return PricingSnapshotRecord(
        id=_PENDING_ID,
        schema_version=1,
        service_kind="llm",
        provider_name="unflushed-provider",
        model="unflushed-model",
        operation="chat",
        source_kind="provider_rate_card",
        currency="USD",
        rates={"input_tokens": {"amount_minor": 1, "per_units": 1, "unit": "token"}},
        source_metadata={},
        retrieved_at=dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
        content_hash=content_hash,
    )


async def _stored_row_count(session_factory: SessionFactory) -> int:
    """Count snapshot rows visible to a fresh session."""
    async with session_factory() as session:
        result = await session.scalar(
            sa.select(sa.func.count()).select_from(PricingSnapshotRecord)
        )
    return typ.cast("int", result)


async def _ensure_in_its_own_transaction(
    session_factory: SessionFactory,
) -> EnsuredPricingSnapshot:
    """Persist the fixture snapshot in a committed transaction."""
    async with session_factory() as session:
        ensured = await SqlAlchemyPricingSnapshotStore(session).ensure(
            v1_pricing_snapshot()
        )
        await session.commit()
    return ensured


@pytest.mark.asyncio
async def test_ensure_uses_the_injected_identifier_factory(
    session_factory: SessionFactory,
) -> None:
    """A new row must take its identifier from the injected factory."""
    chosen = uuid.UUID(int=4242)
    calls: list[int] = []

    def fixed_factory() -> uuid.UUID:
        """Return the same identifier on every call, recording each call."""
        calls.append(1)
        return chosen

    async with session_factory() as session:
        store = SqlAlchemyPricingSnapshotStore(session, uuid_factory=fixed_factory)
        ensured = await store.ensure(v1_pricing_snapshot())
        await session.commit()

    assert ensured.outcome is SnapshotEnsureOutcome.PERSISTED, (
        "the first ensure must insert the row"
    )
    assert ensured.pricing_snapshot_id == PricingSnapshotId(str(chosen)), (
        "the stored identifier must come from the injected factory"
    )
    assert len(calls) == 1, f"the factory must supply exactly one identifier: {calls}"


@pytest.mark.asyncio
async def test_get_leaves_a_pending_write_unflushed(
    session_factory: SessionFactory,
) -> None:
    """A read must not flush work the caller has staged but not committed."""
    ensured = await _ensure_in_its_own_transaction(session_factory)

    async with session_factory() as session:
        store = SqlAlchemyPricingSnapshotStore(session)
        session.add(_pending_record("sha256:pending-read"))
        await store.get(ensured.pricing_snapshot_id)
        assert _PENDING_ID in {row.id for row in session.new}, (
            "the staged row must still be pending after a read"
        )

    assert await _stored_row_count(session_factory) == 1, (
        "the read must not have written the staged row"
    )


@pytest.mark.asyncio
async def test_ensure_reuses_a_row_without_rewriting_it(
    session_factory: SessionFactory,
) -> None:
    """Reusing a snapshot must not touch the stored row or its identity."""
    first = await _ensure_in_its_own_transaction(session_factory)

    async with session_factory() as session:
        second = await SqlAlchemyPricingSnapshotStore(session).ensure(
            v1_pricing_snapshot()
        )
        record = await session.get(
            PricingSnapshotRecord,
            uuid.UUID(str(first.pricing_snapshot_id)),
        )
        dirty = list(session.dirty)
        await session.commit()

    assert second.outcome is SnapshotEnsureOutcome.REUSED, (
        "matching content must reuse the stored row"
    )
    assert second.pricing_snapshot_id == first.pricing_snapshot_id, (
        "reuse must return the identifier already stored"
    )
    assert record is not None, "the reused row must still exist"
    assert record.id == uuid.UUID(str(first.pricing_snapshot_id)), (
        "reuse must not reassign the row identity"
    )
    assert not dirty, (
        f"reuse must leave the stored row unmodified, but these are dirty: {dirty!r}"
    )
    assert await _stored_row_count(session_factory) == 1, (
        "reuse must not insert a second row"
    )


@pytest.mark.asyncio
async def test_get_reports_a_malformed_identifier_as_not_found(
    session_factory: SessionFactory,
) -> None:
    """An identifier that is not a UUID is a miss, not an internal error."""
    async with session_factory() as session:
        store = SqlAlchemyPricingSnapshotStore(session)
        with pytest.raises(PricingSnapshotNotFoundError):
            await store.get(PricingSnapshotId("not-a-uuid"))
