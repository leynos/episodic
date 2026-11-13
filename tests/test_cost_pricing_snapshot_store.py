"""Content addressing, round-trip, and tamper detection for snapshot storage."""

import datetime as dt
import typing as typ
import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from episodic.cost import (
    BillingPeriodKey,
    PricingSnapshotError,
    PricingSnapshotId,
    PricingSnapshotIntegrityError,
    PricingSnapshotNotFoundError,
    RunPricingKey,
    SnapshotEnsureOutcome,
)
from episodic.cost.pricing_snapshot_hash import PRICING_SNAPSHOT_V1_FIELDS
from episodic.cost.storage import (
    PricingSnapshotRecord,
    SqlAlchemyCostLedgerStore,
    SqlAlchemyPricingSnapshotStore,
)
from tests.fixtures.cost import v1_pricing_snapshot

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    type SessionFactory = async_sessionmaker[AsyncSession]
else:  # pragma: no cover - runtime alias for evaluated test annotations.
    type SessionFactory = object


# Every field the version 1 canonical document hashes, mapped to the columns
# that persist it. A source document occupies a media type and its content.
_PRICING_SNAPSHOT_FIELD_COLUMNS: typ.Final[dict[str, tuple[str, ...]]] = {
    "currency": ("currency",),
    "effective_from": ("effective_from",),
    "model": ("model",),
    "operation": ("operation",),
    "provider_name": ("provider_name",),
    "rates": ("rates",),
    "retrieved_at": ("retrieved_at",),
    "schema_version": ("schema_version",),
    "service_kind": ("service_kind",),
    "source_document": ("source_document_media_type", "source_document_content"),
    "source_kind": ("source_kind",),
    "source_metadata": ("source_metadata",),
}

# A differing value for each field, keyed by the columns it writes. The values
# stay valid for the domain so only the content hash exposes the change.
_TAMPERED_VALUES: typ.Final[dict[str, dict[str, object]]] = {
    "currency": {"currency": "EUR"},
    "effective_from": {"effective_from": dt.datetime(2026, 7, 1, tzinfo=dt.UTC)},
    "model": {"model": "gpt-4.1-mini"},
    "operation": {"operation": "responses"},
    "provider_name": {"provider_name": "azure"},
    "rates": {
        "rates": {"input_tokens": {"amount_minor": 1, "per_units": 1, "unit": "token"}}
    },
    "retrieved_at": {"retrieved_at": dt.datetime(2026, 6, 5, tzinfo=dt.UTC)},
    "schema_version": {"schema_version": 2},
    "service_kind": {"service_kind": "tts"},
    "source_document": {
        "source_document_media_type": "text/plain",
        "source_document_content": "forged source document",
    },
    "source_kind": {"source_kind": "forged_rate_card"},
    "source_metadata": {"source_metadata": {"source_url": "https://forged.test/x"}},
}

# Each differing value violates a check constraint, so the database refuses it.
_CONSTRAINT_REFUSALS: typ.Final[dict[str, str]] = {
    "schema_version": "ck_pricing_snapshots_schema_version",
    "source_kind": "ck_pricing_snapshots_source_kind",
}


async def _tamper_stored_rates(
    session_factory: SessionFactory,
    identifier: PricingSnapshotId,
) -> None:
    """Corrupt one stored row's rates without changing its content hash."""
    async with session_factory() as session:
        await session.execute(
            sa
            .update(PricingSnapshotRecord)
            .where(PricingSnapshotRecord.id == uuid.UUID(str(identifier)))
            .values(
                rates={
                    "input_tokens": {
                        "amount_minor": 99,
                        "per_units": 1,
                        "unit": "token",
                    }
                }
            )
        )
        await session.commit()


async def _tamper_stored_columns(
    session_factory: SessionFactory,
    identifier: PricingSnapshotId,
    values: dict[str, object],
) -> None:
    """Overwrite stored columns directly without recomputing the hash."""
    async with session_factory() as session:
        await session.execute(
            sa
            .update(PricingSnapshotRecord)
            .where(PricingSnapshotRecord.id == uuid.UUID(str(identifier)))
            .values(**values)
        )
        await session.commit()


@pytest.mark.asyncio
async def test_ensure_is_content_addressed(session_factory: SessionFactory) -> None:
    """Equal content reuses one row even when built by separate calls."""
    async with session_factory() as session:
        snapshots = SqlAlchemyPricingSnapshotStore(session)
        first = await snapshots.ensure(v1_pricing_snapshot())
        second = await snapshots.ensure(v1_pricing_snapshot())
        await session.commit()

    assert first.outcome is SnapshotEnsureOutcome.PERSISTED, (
        "the first ensure must insert the row"
    )
    assert second.outcome is SnapshotEnsureOutcome.REUSED, (
        "the second ensure must reuse the row"
    )
    assert first.pricing_snapshot_id == second.pricing_snapshot_id, (
        "equal content must resolve to one stored snapshot"
    )


@pytest.mark.asyncio
async def test_ensure_stores_exactly_one_row(session_factory: SessionFactory) -> None:
    """Repeated ensures never duplicate a content-addressed row."""
    async with session_factory() as session:
        snapshots = SqlAlchemyPricingSnapshotStore(session)
        for _ in range(3):
            await snapshots.ensure(v1_pricing_snapshot())
        await session.commit()

    async with session_factory() as session:
        count = (
            await session.execute(sa.select(sa.func.count(PricingSnapshotRecord.id)))
        ).scalar_one()

    assert count == 1, "content addressing must keep one row per distinct content"


@pytest.mark.asyncio
async def test_get_round_trips_the_snapshot(session_factory: SessionFactory) -> None:
    """A stored snapshot reads back field-for-field identical."""
    original = v1_pricing_snapshot()
    async with session_factory() as session:
        ensured = await SqlAlchemyPricingSnapshotStore(session).ensure(original)
        await session.commit()

    async with session_factory() as session:
        stored = await SqlAlchemyPricingSnapshotStore(session).get(
            ensured.pricing_snapshot_id
        )

    assert stored == original, "the stored row must rebuild the exact snapshot"
    assert stored.content_hash == original.content_hash, (
        "the round trip must preserve the content hash"
    )
    assert dict(stored.rates) == dict(original.rates), (
        "the round trip must preserve the exact rates"
    )


@pytest.mark.asyncio
async def test_get_rejects_a_tampered_row(session_factory: SessionFactory) -> None:
    """A row whose content no longer matches its hash is refused."""
    async with session_factory() as session:
        ensured = await SqlAlchemyPricingSnapshotStore(session).ensure(
            v1_pricing_snapshot()
        )
        await session.commit()

    await _tamper_stored_rates(session_factory, ensured.pricing_snapshot_id)

    async with session_factory() as session:
        snapshots = SqlAlchemyPricingSnapshotStore(session)
        with pytest.raises(PricingSnapshotIntegrityError, match="content hash"):
            await snapshots.get(ensured.pricing_snapshot_id)

    assert issubclass(PricingSnapshotIntegrityError, PricingSnapshotError), (
        "integrity failures must remain pricing snapshot failures"
    )


@pytest.mark.asyncio
async def test_ensure_verifies_a_row_before_reusing_it(
    session_factory: SessionFactory,
) -> None:
    """A tampered row is refused rather than handed back as reusable."""
    original = v1_pricing_snapshot()
    async with session_factory() as session:
        ensured = await SqlAlchemyPricingSnapshotStore(session).ensure(original)
        await session.commit()

    await _tamper_stored_rates(session_factory, ensured.pricing_snapshot_id)

    async with session_factory() as session:
        snapshots = SqlAlchemyPricingSnapshotStore(session)

        with pytest.raises(PricingSnapshotIntegrityError, match="content hash"):
            await snapshots.ensure(original)


@pytest.mark.asyncio
async def test_get_ignores_a_row_cached_before_tampering(
    session_factory: SessionFactory,
) -> None:
    """A row already loaded in the session must not mask later corruption."""
    async with session_factory() as session:
        snapshots = SqlAlchemyPricingSnapshotStore(session)
        ensured = await snapshots.ensure(v1_pricing_snapshot())
        await session.commit()
        # Each transaction below ends without expiring. Retaining the row keeps
        # it in the identity map, which holds rows weakly, so a later read
        # would otherwise be answered from these attributes.
        retained = await session.get(
            PricingSnapshotRecord,
            uuid.UUID(str(ensured.pricing_snapshot_id)),
        )
        assert retained is not None, "the stored row must load"
        await session.commit()

        await _tamper_stored_rates(session_factory, ensured.pricing_snapshot_id)

        with pytest.raises(PricingSnapshotIntegrityError, match="content hash"):
            await snapshots.get(ensured.pricing_snapshot_id)


@pytest.mark.asyncio
async def test_ensure_ignores_a_row_cached_before_tampering(
    session_factory: SessionFactory,
) -> None:
    """Conflict reuse must verify the stored row, not a cached copy of it."""
    async with session_factory() as session:
        snapshots = SqlAlchemyPricingSnapshotStore(session)
        ensured = await snapshots.ensure(v1_pricing_snapshot())
        await session.commit()
        retained = await session.get(
            PricingSnapshotRecord,
            uuid.UUID(str(ensured.pricing_snapshot_id)),
        )
        assert retained is not None, "the stored row must load"
        await session.commit()

        await _tamper_stored_rates(session_factory, ensured.pricing_snapshot_id)

        with pytest.raises(PricingSnapshotIntegrityError, match="content hash"):
            await snapshots.ensure(v1_pricing_snapshot())


def test_tamper_cases_cover_every_hashed_field() -> None:
    """Every field the version 1 hash covers has a tamper case."""
    assert set(_PRICING_SNAPSHOT_FIELD_COLUMNS) == set(PRICING_SNAPSHOT_V1_FIELDS), (
        "a new hashed field must gain a column mapping and a tamper case"
    )
    assert set(_TAMPERED_VALUES) == set(_PRICING_SNAPSHOT_FIELD_COLUMNS), (
        "every hashed field must have a differing value to write"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("field", tuple(_PRICING_SNAPSHOT_FIELD_COLUMNS))
async def test_tampering_a_hashed_column_is_detected(
    session_factory: SessionFactory,
    field: str,
) -> None:
    """A direct SQL edit to any hashed column fails the content hash check.

    ``schema_version`` and ``source_kind`` never reach that check: every value
    differing from the stored one violates their check constraint, so the
    database refuses the write before a read could observe the tamper.
    """
    async with session_factory() as session:
        ensured = await SqlAlchemyPricingSnapshotStore(session).ensure(
            v1_pricing_snapshot()
        )
        await session.commit()

    tampered = _TAMPERED_VALUES[field]
    refusal = _CONSTRAINT_REFUSALS.get(field)
    if refusal is not None:
        with pytest.raises(IntegrityError, match=refusal):
            await _tamper_stored_columns(
                session_factory, ensured.pricing_snapshot_id, tampered
            )
        return

    await _tamper_stored_columns(session_factory, ensured.pricing_snapshot_id, tampered)
    async with session_factory() as session:
        snapshots = SqlAlchemyPricingSnapshotStore(session)

        with pytest.raises(PricingSnapshotIntegrityError, match="content hash"):
            await snapshots.get(ensured.pricing_snapshot_id)


@pytest.mark.asyncio
async def test_altering_recorded_at_is_not_tampering(
    session_factory: SessionFactory,
) -> None:
    """The non-hashed recorded_at column may change without failing a read."""
    original = v1_pricing_snapshot()
    async with session_factory() as session:
        ensured = await SqlAlchemyPricingSnapshotStore(session).ensure(original)
        await session.commit()

    await _tamper_stored_columns(
        session_factory,
        ensured.pricing_snapshot_id,
        {"recorded_at": dt.datetime(2020, 1, 1, tzinfo=dt.UTC)},
    )

    async with session_factory() as session:
        stored = await SqlAlchemyPricingSnapshotStore(session).get(
            ensured.pricing_snapshot_id
        )

    assert stored == original, (
        "a column outside the content hash must not invalidate a stored snapshot"
    )


@pytest.mark.asyncio
async def test_ensure_satisfies_a_run_pricing_pin(
    session_factory: SessionFactory,
) -> None:
    """A persisted snapshot identifier satisfies the pin foreign key."""
    async with session_factory() as session:
        ensured = await SqlAlchemyPricingSnapshotStore(session).ensure(
            v1_pricing_snapshot()
        )
        await SqlAlchemyCostLedgerStore(session).pin_run_pricing(
            RunPricingKey(
                workflow_run_id="workflow-run-ensure",
                provider_name="openai",
                model="gpt-4o-mini",
                operation="chat_completions",
                billing_period_key=BillingPeriodKey("2026-06"),
            ),
            ensured.pricing_snapshot_id,
            "2026-06-04T10:00:00Z",
        )
        await session.commit()

    async with session_factory() as session:
        pinned = await SqlAlchemyCostLedgerStore(session).get_run_pricing_pin(
            RunPricingKey(
                workflow_run_id="workflow-run-ensure",
                provider_name="openai",
                model="gpt-4o-mini",
                operation="chat_completions",
                billing_period_key=BillingPeriodKey("2026-06"),
            )
        )

    assert pinned == ensured.pricing_snapshot_id, (
        "the pin must reference the content-addressed snapshot"
    )


@pytest.mark.asyncio
async def test_get_reports_an_unknown_identifier(
    session_factory: SessionFactory,
) -> None:
    """An unknown or malformed identifier raises the not-found error."""
    async with session_factory() as session:
        snapshots = SqlAlchemyPricingSnapshotStore(session)

        with pytest.raises(PricingSnapshotNotFoundError, match="No pricing snapshot"):
            await snapshots.get(
                PricingSnapshotId("018f15f8-8c12-7c3a-9e9f-9f8f8f8f8f96")
            )

        with pytest.raises(PricingSnapshotNotFoundError, match="No pricing snapshot"):
            await snapshots.get(PricingSnapshotId("not-a-uuid"))

    assert issubclass(PricingSnapshotNotFoundError, LookupError), (
        "callers that already catch LookupError must keep working"
    )
