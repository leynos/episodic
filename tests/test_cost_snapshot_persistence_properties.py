"""Property tests for idempotent, immutable pricing-snapshot persistence."""

import typing as typ
import uuid

import hypothesis.strategies as st
import pytest
import sqlalchemy as sa
from hypothesis import HealthCheck, given, settings

from episodic.cost import (
    BillingPeriodKey,
    CurrencyCode,
    PricingSnapshot,
    PricingSnapshotCollisionError,
    PricingSnapshotId,
    PricingSourceKind,
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
    {"input_tokens": 100, "output_tokens": 200},
    {"input_tokens": 150, "output_tokens": 250},
)

_OPERATIONS = st.lists(
    st.tuples(
        st.integers(min_value=0, max_value=1),
        st.integers(min_value=0, max_value=1),
        st.integers(min_value=0, max_value=1),
    ),
    min_size=1,
    max_size=6,
)


def _snapshot(
    snapshot_id: str,
    content_hash: str,
    rates: dict[str, int],
) -> PricingSnapshot:
    """Build a pricing snapshot from the example's finite domains."""
    return PricingSnapshot(
        pricing_snapshot_id=PricingSnapshotId(snapshot_id),
        provider_name="openai",
        model="gpt-4o-mini",
        operation="chat_completions",
        source_kind=PricingSourceKind.PROVIDER_RATE_CARD,
        currency=CurrencyCode("USD"),
        billing_period_key=BillingPeriodKey("2026-06"),
        rates_minor_per_metric=rates,
        source_metadata={"source": "property-test"},
        content_hash=content_hash,
        retrieved_at="2026-06-04T09:00:00Z",
    )


@given(operations=_OPERATIONS)
@settings(
    max_examples=6,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@pytest.mark.asyncio
async def test_ensure_snapshot_keeps_persisted_identifiers_immutable(
    session_factory: SessionFactory,
    operations: list[tuple[int, int, int]],
) -> None:
    """No operation ordering can mutate a persisted snapshot identifier."""
    # This function-scoped database persists rows across Hypothesis examples,
    # which may reuse generated UUIDs. Give each example a fresh storage scope.
    scope = uuid.uuid4()
    identifiers = (str(uuid.uuid5(scope, "id-0")), str(uuid.uuid5(scope, "id-1")))
    hashes = (f"hash-{scope}-0", f"hash-{scope}-1")
    recorded: dict[str, tuple[str, dict[str, int]]] = {}
    claimed_hashes: dict[str, str] = {}

    for id_index, hash_index, rates_index in operations:
        snapshot = _snapshot(
            identifiers[id_index],
            hashes[hash_index],
            _RATE_VARIANTS[rates_index],
        )
        snapshot_id = identifiers[id_index]
        content_hash = hashes[hash_index]
        async with session_factory() as session:
            store = SqlAlchemyPricingSnapshotStore(session)
            if (
                snapshot_id not in recorded
                and claimed_hashes.get(content_hash, snapshot_id) != snapshot_id
            ):
                with pytest.raises(PricingSnapshotCollisionError):
                    await store.ensure(snapshot)
                continue
            await store.ensure(snapshot)
            await session.commit()
        if snapshot_id not in recorded:
            recorded[snapshot_id] = (content_hash, _RATE_VARIANTS[rates_index])
            claimed_hashes[content_hash] = snapshot_id

    async with session_factory() as session:
        for snapshot_id, (content_hash, rates) in recorded.items():
            stored_hash, stored_rates = (
                await session.execute(
                    sa.select(
                        PricingSnapshotRecord.content_hash,
                        PricingSnapshotRecord.rates_minor_per_metric,
                    ).where(PricingSnapshotRecord.id == uuid.UUID(snapshot_id))
                )
            ).one()
            assert stored_hash == content_hash, (
                f"snapshot {snapshot_id} changed its content hash; "
                f"expected {content_hash!r}, got {stored_hash!r}"
            )
            assert stored_rates == rates, (
                f"snapshot {snapshot_id} changed its rates; "
                f"expected {rates!r}, got {stored_rates!r}"
            )
