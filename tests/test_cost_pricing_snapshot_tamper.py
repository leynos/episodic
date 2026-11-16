"""Tamper detection for every column the version 1 content hash covers.

A stored row is trusted only while its columns still hash to the recorded
content hash. Each case edits stored columns directly, without recomputing the
hash, and asserts that a read refuses the row. The one case the database itself
refuses is asserted as a constraint refusal, because no read can observe a
write the database rejected.

Source-document columns are edited one at a time: the pair constraint allows
either column to change while the other keeps the row valid, so a combined edit
would not prove each column is hashed.
"""

import dataclasses as dc
import datetime as dt
import typing as typ
import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from episodic.cost import (
    PricingSnapshotId,
    PricingSnapshotIntegrityError,
    PricingSourceKind,
)
from episodic.cost.pricing_snapshot import (
    PricingSnapshot,
    SourceDocument,
)
from episodic.cost.pricing_snapshot_hash import PRICING_SNAPSHOT_V1_FIELDS
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
# stay valid for the domain so only the content hash exposes the change. A
# field with several cases has one case per stored column.
_TAMPERED_VALUES: typ.Final[dict[str, tuple[dict[str, object], ...]]] = {
    "currency": ({"currency": "EUR"},),
    "effective_from": ({"effective_from": dt.datetime(2026, 7, 1, tzinfo=dt.UTC)},),
    "model": ({"model": "gpt-4.1-mini"},),
    "operation": ({"operation": "responses"},),
    "provider_name": ({"provider_name": "azure"},),
    "rates": (
        {
            "rates": {
                "input_tokens": {"amount_minor": 1, "per_units": 1, "unit": "token"}
            }
        },
    ),
    "retrieved_at": ({"retrieved_at": dt.datetime(2026, 6, 5, tzinfo=dt.UTC)},),
    "schema_version": ({"schema_version": 2},),
    "service_kind": ({"service_kind": "tts"},),
    "source_document": (
        {"source_document_content": "forged source document"},
        {"source_document_media_type": "text/plain"},
    ),
    "source_kind": ({"source_kind": "provider_rate_card"},),
    "source_metadata": ({"source_metadata": {"source_url": "https://forged.test/x"}},),
}

# Each differing value violates a check constraint, so the database refuses it.
_CONSTRAINT_REFUSALS: typ.Final[dict[str, str]] = {
    "schema_version": "ck_pricing_snapshots_schema_version",
}

# Fields whose stored row must carry a source document for the edit to be valid.
_DOCUMENT_FIELDS: typ.Final[frozenset[str]] = frozenset({
    "source_document",
    "source_kind",
})

_PLAN_DOCUMENT: typ.Final[SourceDocument] = SourceDocument(
    media_type="application/json",
    content='{"plan": "forged"}',
)

_TAMPER_PARAMS = [
    pytest.param(field, values, id=f"{field}-{index}")
    for field, cases in _TAMPERED_VALUES.items()
    for index, values in enumerate(cases, start=1)
]


def _plan_snapshot() -> PricingSnapshot:
    """Build a stored snapshot that carries a source document."""
    return dc.replace(
        v1_pricing_snapshot(),
        source_kind=PricingSourceKind.SLA4OAI_PLAN,
        source_document=_PLAN_DOCUMENT,
    )


def _stored_snapshot(field: str) -> PricingSnapshot:
    """Return the snapshot whose stored row accepts this field's edit."""
    return _plan_snapshot() if field in _DOCUMENT_FIELDS else v1_pricing_snapshot()


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


async def _store(session_factory: SessionFactory, field: str) -> PricingSnapshotId:
    """Persist the row this field's edit starts from and return its identity."""
    async with session_factory() as session:
        ensured = await SqlAlchemyPricingSnapshotStore(session).ensure(
            _stored_snapshot(field)
        )
        await session.commit()
    return ensured.pricing_snapshot_id


def test_tamper_cases_cover_every_hashed_field() -> None:
    """Every field the version 1 hash covers has a tamper case."""
    assert set(_PRICING_SNAPSHOT_FIELD_COLUMNS) == set(PRICING_SNAPSHOT_V1_FIELDS), (
        "a new hashed field must gain a column mapping and a tamper case"
    )
    assert set(_TAMPERED_VALUES) == set(_PRICING_SNAPSHOT_FIELD_COLUMNS), (
        "every hashed field must have a differing value to write"
    )


def test_source_document_columns_are_tampered_independently() -> None:
    """Each stored source-document column is edited on its own."""
    cases = _TAMPERED_VALUES["source_document"]
    edited = [set(case) for case in cases]
    assert set().union(*edited) == set(
        _PRICING_SNAPSHOT_FIELD_COLUMNS["source_document"]
    ), "every source-document column must have its own tamper case"
    assert all(len(columns) == 1 for columns in edited), (
        "a combined edit would not prove each column is hashed"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(("field", "values"), _TAMPER_PARAMS)
async def test_tampering_a_hashed_column_is_detected(
    session_factory: SessionFactory,
    field: str,
    values: dict[str, object],
) -> None:
    """A direct SQL edit to any hashed column fails the content hash check.

    ``schema_version`` never reaches that check: every value differing from the
    stored one violates its check constraint, so the database refuses the write
    before a read could observe the tamper.
    """
    identifier = await _store(session_factory, field)

    refusal = _CONSTRAINT_REFUSALS.get(field)
    if refusal is not None:
        with pytest.raises(IntegrityError, match=refusal):
            await _tamper_stored_columns(session_factory, identifier, values)
        return

    await _tamper_stored_columns(session_factory, identifier, values)
    async with session_factory() as session:
        with pytest.raises(PricingSnapshotIntegrityError, match="content hash"):
            await SqlAlchemyPricingSnapshotStore(session).get(identifier)


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
