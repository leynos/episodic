"""Property tests for idempotent, immutable pricing-snapshot persistence."""

import datetime as dt
import typing as typ
import uuid

import hypothesis.strategies as st
import pytest
import sqlalchemy as sa
from hypothesis import HealthCheck, event, given, settings

from episodic.cost import (
    CurrencyCode,
    PricingSnapshotIntegrityError,
    PricingSourceKind,
    SnapshotEnsureOutcome,
)
from episodic.cost.pricing_snapshot import (
    MeteredRate,
    PricedService,
    PricingSnapshot,
    SourceDocument,
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

# Sequences must draw both contents and repeat at least one of them, so the
# repeat and distinct-content classes are reachable in every example.
_OPERATIONS = st.lists(
    st.integers(min_value=0, max_value=1),
    min_size=3,
    max_size=6,
).filter(lambda operations: set(operations) == {0, 1})

# Hypothesis requires naive bounds when a timezone is attached afterwards.
# They stay well inside years 2000-2099 once a +/-14h offset is applied, so
# converting the generated instant to UTC can never overflow a datetime.
_NAIVE_INSTANTS = st.datetimes(
    min_value=dt.datetime(2001, 1, 1),  # ruff: ignore[call-datetime-without-tzinfo]
    max_value=dt.datetime(2098, 12, 31),  # ruff: ignore[call-datetime-without-tzinfo]
)
_NON_UTC_OFFSETS = st.one_of(
    st.integers(min_value=-720, max_value=-1),
    st.integers(min_value=1, max_value=840),
).map(lambda minutes: dt.timezone(dt.timedelta(minutes=minutes)))
_AWARE_INSTANTS = st.tuples(_NAIVE_INSTANTS, _NON_UTC_OFFSETS).map(
    lambda pair: _with_offset(*pair)
)
_SERVICE_KINDS = st.sampled_from(tuple(PricedService))
_SOURCE_KINDS = st.sampled_from(tuple(PricingSourceKind))


def _with_offset(naive: dt.datetime, offset: dt.timezone) -> dt.datetime:
    """Attach a non-UTC offset and force microsecond precision."""
    return naive.replace(tzinfo=offset, microsecond=naive.microsecond or 1)


def _content_pair() -> list[PricingSnapshot]:
    """Build two contents differing in service kind, source, and rates."""
    retrieved_at = dt.datetime(2026, 6, 4, 9, 15, 30, 123456, tzinfo=dt.UTC)
    return [
        PricingSnapshot(
            service_kind=PricedService.LLM,
            provider_name="openai",
            model="gpt-4o-mini",
            operation="chat_completions",
            source_kind=PricingSourceKind.PROVIDER_RATE_CARD,
            currency=CurrencyCode("USD"),
            rates={
                "input_tokens": MeteredRate.reduced(100, 1_000_000, UsageUnit.TOKEN),
                "output_tokens": MeteredRate.reduced(200, 1_000_000, UsageUnit.TOKEN),
            },
            source_metadata={"source": "property-test"},
            retrieved_at=retrieved_at,
        ),
        PricingSnapshot(
            service_kind=PricedService.TTS,
            provider_name="elevenlabs",
            model="voice-1",
            operation="text_to_speech",
            source_kind=PricingSourceKind.SLA4OAI_PLAN,
            currency=CurrencyCode("EUR"),
            rates={
                "input_characters": MeteredRate.reduced(3, 1_000, UsageUnit.CHARACTER),
            },
            source_metadata={"source": "property-test"},
            source_document=SourceDocument(
                media_type="application/yaml",
                content="plan: tts\n",
            ),
            retrieved_at=retrieved_at,
        ),
    ]


@st.composite
def _pricing_snapshots(draw: st.DrawFn) -> PricingSnapshot:
    """Generate a snapshot spanning every persisted dimension."""
    token = draw(st.uuids())
    service_kind = draw(_SERVICE_KINDS)
    source_kind = draw(_SOURCE_KINDS)
    retrieved_at = draw(_AWARE_INSTANTS)
    effective_from = draw(st.none() | _AWARE_INSTANTS)
    source_document = (
        SourceDocument(
            media_type="application/yaml",
            content=f"plan: {token}\n",
        )
        if source_kind is PricingSourceKind.SLA4OAI_PLAN
        else None
    )
    return PricingSnapshot(
        service_kind=service_kind,
        provider_name=f"provider-{token.hex[:8]}",
        model="model-1",
        operation="operation_1",
        source_kind=source_kind,
        currency=CurrencyCode("USD"),
        rates={"input_tokens": MeteredRate.reduced(15, 1_000_000, UsageUnit.TOKEN)},
        source_metadata={"example": str(token)},
        retrieved_at=retrieved_at,
        effective_from=effective_from,
        source_document=source_document,
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


async def _stored_hashes(
    session_factory: SessionFactory,
    content_hashes: set[str],
) -> set[str]:
    """Return which content hashes already have a stored row."""
    async with session_factory() as session:
        rows = await session.execute(
            sa.select(PricingSnapshotRecord.content_hash).where(
                PricingSnapshotRecord.content_hash.in_(content_hashes)
            )
        )
        return set(rows.scalars())


async def _ensure_checked(
    session_factory: SessionFactory,
    snapshot: PricingSnapshot,
    identifiers: dict[str, object],
    already_stored: set[str],
) -> bool:
    """Ensure one snapshot, assert its outcome, and report a repeat."""
    async with session_factory() as session:
        ensured = await SqlAlchemyPricingSnapshotStore(session).ensure(snapshot)
        await session.commit()
    is_repeat = snapshot.content_hash in identifiers
    event("repeated content" if is_repeat else "distinct content")
    was_stored = is_repeat or snapshot.content_hash in already_stored
    expected = (
        SnapshotEnsureOutcome.REUSED if was_stored else SnapshotEnsureOutcome.PERSISTED
    )
    assert ensured.outcome is expected, (
        "ensure must persist new content and reuse stored content"
    )
    event(f"outcome {ensured.outcome.value}")
    previous = identifiers.setdefault(
        snapshot.content_hash,
        ensured.pricing_snapshot_id,
    )
    assert ensured.pricing_snapshot_id == previous, (
        "equal content must always resolve to the same stored identifier"
    )
    return is_repeat


async def _assert_one_immutable_row_per_content(
    session_factory: SessionFactory,
    snapshots: list[PricingSnapshot],
    identifiers: dict[str, object],
) -> None:
    """Assert exactly one unchanged row exists per content hash."""
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
        assert str(row.id) == identifiers[row.content_hash], (
            f"snapshot {row.content_hash} was rewritten under a new identifier"
        )
        assert row.rates == _stored_rates(expected), (
            f"snapshot {row.content_hash} changed its rates"
        )


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
    snapshots = _content_pair()
    # Persisted rows outlive Hypothesis examples in the shared database
    # fixture, so a first call in this example may reuse an earlier row.
    already_stored = await _stored_hashes(
        session_factory,
        {snapshot.content_hash for snapshot in snapshots},
    )
    identifiers: dict[str, object] = {}
    repeats = 0

    for index in operations:
        snapshot = snapshots[index]
        repeats += await _ensure_checked(
            session_factory,
            snapshot,
            identifiers,
            already_stored,
        )

    assert len(identifiers) == len(snapshots), (
        "the sequence must exercise both distinct contents"
    )
    assert repeats >= 1, "the sequence must repeat at least one content"
    # Only this example's content hashes are in scope: rows from earlier
    # examples share the database.
    await _assert_one_immutable_row_per_content(
        session_factory,
        snapshots,
        identifiers,
    )


@given(snapshot=_pricing_snapshots())
@settings(
    max_examples=6,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@pytest.mark.asyncio
async def test_ensure_then_get_round_trips_every_field(
    session_factory: SessionFactory,
    snapshot: PricingSnapshot,
) -> None:
    """A stored snapshot reads back equal, microseconds and offsets intact."""
    assert snapshot.retrieved_at.microsecond != 0, (
        "the property must exercise microsecond precision"
    )
    assert snapshot.retrieved_at.utcoffset() != dt.timedelta(0), (
        "the property must exercise non-UTC instants"
    )
    event(f"service {snapshot.service_kind.value}")
    event(f"source {snapshot.source_kind.value}")
    event(
        "source_document present"
        if snapshot.source_document is not None
        else "source_document absent"
    )
    event(
        "effective_from present"
        if snapshot.effective_from is not None
        else "effective_from absent"
    )

    async with session_factory() as session:
        ensured = await SqlAlchemyPricingSnapshotStore(session).ensure(snapshot)
        await session.commit()

    async with session_factory() as session:
        stored = await SqlAlchemyPricingSnapshotStore(session).get(
            ensured.pricing_snapshot_id
        )

    assert stored == snapshot, "a stored snapshot must read back unchanged"
    assert stored.content_hash == snapshot.content_hash, (
        "the integrity check must preserve the content identity"
    )


@pytest.mark.asyncio
async def test_get_rejects_retrieved_at_truncated_to_seconds(
    session_factory: SessionFactory,
) -> None:
    """Rounding a stored instant down to seconds breaks the integrity check."""
    retrieved_at = dt.datetime(
        2026,
        6,
        4,
        9,
        15,
        30,
        123456,
        tzinfo=dt.timezone(dt.timedelta(hours=5, minutes=30)),
    )
    snapshot = PricingSnapshot(
        service_kind=PricedService.LLM,
        provider_name="openai",
        model="gpt-4o-mini",
        operation="chat_completions",
        source_kind=PricingSourceKind.PROVIDER_RATE_CARD,
        currency=CurrencyCode("USD"),
        rates={"input_tokens": MeteredRate.reduced(15, 1_000_000, UsageUnit.TOKEN)},
        source_metadata={"source": "seeded-fault"},
        retrieved_at=retrieved_at,
    )

    async with session_factory() as session:
        ensured = await SqlAlchemyPricingSnapshotStore(session).ensure(snapshot)
        await session.commit()

    # The untampered row must already round-trip its microseconds, so the
    # failure below can only come from the truncation.
    async with session_factory() as session:
        stored = await SqlAlchemyPricingSnapshotStore(session).get(
            ensured.pricing_snapshot_id
        )
    assert stored.retrieved_at.microsecond == 123456, (
        "the stored row must retain microsecond precision before the fault"
    )

    # The seeded fault edits the stored instant only, leaving content_hash at
    # its recorded value so the corruption is invisible to a plain read.
    async with session_factory() as session:
        await session.execute(
            sa
            .update(PricingSnapshotRecord)
            .where(
                PricingSnapshotRecord.id == uuid.UUID(str(ensured.pricing_snapshot_id))
            )
            .values(retrieved_at=retrieved_at.replace(microsecond=0))
        )
        await session.commit()

    async with session_factory() as session:
        with pytest.raises(PricingSnapshotIntegrityError):
            await SqlAlchemyPricingSnapshotStore(session).get(
                ensured.pricing_snapshot_id
            )
