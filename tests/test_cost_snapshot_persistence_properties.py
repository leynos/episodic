"""Property tests for idempotent, immutable pricing-snapshot persistence."""

import datetime as dt
import typing as typ

import hypothesis.strategies as st
import pytest
import sqlalchemy as sa
from hypothesis import HealthCheck, given, settings

from episodic.cost import CurrencyCode, PricingSourceKind
from episodic.cost.pricing_snapshot import (
    MeteredRate,
    PricedService,
    PricingSnapshot,
    UsageUnit,
)
from episodic.cost.storage import (
    PricingSnapshotRecord,
    SqlAlchemyPricingSnapshotStore,
)

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    type SessionFactory = async_sessionmaker[AsyncSession]
else:  # pragma: no cover - runtime alias for evaluated test annotations.
    type SessionFactory = object

_RATE_VARIANTS = (
    {"input_tokens": MeteredRate.reduced(100, 1_000_000, UsageUnit.TOKEN)},
    {"input_tokens": MeteredRate.reduced(150, 1_000_000, UsageUnit.TOKEN)},
)

_OPERATIONS = st.lists(
    st.integers(min_value=0, max_value=len(_RATE_VARIANTS) - 1),
    min_size=1,
    max_size=6,
)


def _snapshot(rates: dict[str, MeteredRate]) -> PricingSnapshot:
    """Build a pricing snapshot from the example's finite domains."""
    return PricingSnapshot(
        service_kind=PricedService.LLM,
        provider_name="openai",
        model="gpt-4o-mini",
        operation="chat_completions",
        source_kind=PricingSourceKind.PROVIDER_RATE_CARD,
        currency=CurrencyCode("USD"),
        rates=rates,
        source_metadata={"source": "property-test"},
        retrieved_at=dt.datetime(2026, 6, 4, 9, tzinfo=dt.UTC),
    )


def _stored_rates(snapshot: PricingSnapshot) -> dict[str, dict[str, object]]:
    """Render a snapshot's rates the way the store persists them."""
    return {
        metric: {
            "amount_minor": rate.amount_minor,
            "per_units": rate.per_units,
            "unit": str(rate.unit),
        }
        for metric, rate in snapshot.rates.items()
    }


@given(operations=_OPERATIONS)
@settings(
    max_examples=6,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@pytest.mark.asyncio
async def test_ensure_keeps_one_immutable_row_per_content(
    session_factory: SessionFactory,
    operations: list[int],
) -> None:
    """No operation ordering can duplicate or mutate a content-addressed row."""
    snapshots = [_snapshot(rates) for rates in _RATE_VARIANTS]
    identifiers: dict[str, object] = {}

    for index in operations:
        snapshot = snapshots[index]
        async with session_factory() as session:
            ensured = await SqlAlchemyPricingSnapshotStore(session).ensure(snapshot)
            await session.commit()
        previous = identifiers.setdefault(
            snapshot.content_hash,
            ensured.pricing_snapshot_id,
        )
        assert ensured.pricing_snapshot_id == previous, (
            "equal content must always resolve to the same stored identifier"
        )

    # Persisted rows outlive Hypothesis examples in the shared database
    # fixture, so only this example's content hashes are in scope.
    async with session_factory() as session:
        rows = [
            row
            for row in (
                (await session.execute(sa.select(PricingSnapshotRecord)))
                .scalars()
                .all()
            )
            if row.content_hash in identifiers
        ]

    assert len(rows) == len(identifiers), (
        "content addressing must keep exactly one row per distinct content"
    )
    for row in rows:
        expected = next(
            snapshot
            for snapshot in snapshots
            if snapshot.content_hash == row.content_hash
        )
        assert row.rates == _stored_rates(expected), (
            f"snapshot {row.content_hash} changed its rates"
        )
