"""Shared Hypothesis strategies for pricing snapshot hash properties.

Both `test_cost_pricing_snapshot_hash_properties` (INV-HASH-DET) and
`test_cost_pricing_snapshot_sensitivity_properties` (INV-HASH-SENS) draw from
one snapshot domain, so the strategies live here rather than being duplicated.
"""

import dataclasses as dc
import datetime as dt
import typing as typ

import hypothesis.strategies as st

from episodic.cost.pricing_snapshot import (
    MeteredRate,
    PricedService,
    PricingSnapshot,
    SourceDocument,
    UsageUnit,
)
from episodic.cost.primitives import CurrencyCode, PricingSourceKind

if typ.TYPE_CHECKING:
    import collections.abc as cabc

METRIC_UNITS: cabc.Mapping[str, UsageUnit] = {
    "input_tokens": UsageUnit.TOKEN,
    "output_tokens": UsageUnit.TOKEN,
    "cached_input_tokens": UsageUnit.TOKEN,
    "input_characters": UsageUnit.CHARACTER,
    "output_audio_milliseconds": UsageUnit.MILLISECOND,
    "requests": UsageUnit.REQUEST,
}
CURRENCIES = ("USD", "EUR", "GBP", "JPY", "CHF")
MEDIA_TYPES = ("application/yaml", "application/json", "text/plain")
SCALE_FACTORS = (1, 2, 3, 5, 8)

NAMES = st.from_regex(r"[A-Za-z][A-Za-z0-9_.-]{0,15}", fullmatch=True)
AWARE_INSTANTS = st.datetimes(
    min_value=dt.datetime(2020, 1, 1, tzinfo=dt.UTC),
    max_value=dt.datetime(2030, 1, 1, tzinfo=dt.UTC),
    timezones=st.just(dt.UTC),
)
METADATA = st.dictionaries(
    keys=st.from_regex(r"[a-z][a-z0-9_]{0,12}", fullmatch=True),
    values=st.text(max_size=16),
    max_size=3,
)
SOURCE_DOCUMENTS = st.builds(
    SourceDocument,
    media_type=st.sampled_from(MEDIA_TYPES),
    content=st.text(max_size=40),
)


@dc.dataclass(frozen=True, slots=True)
class Subject:
    """The identity fields every snapshot variant shares."""

    service_kind: PricedService
    source_kind: PricingSourceKind
    currency: CurrencyCode
    provider_name: str
    model: str
    operation: str


@dc.dataclass(frozen=True, slots=True)
class AuthoredRates:
    """One rate map authored at two different integer scales."""

    base: dict[str, MeteredRate]
    scaled: dict[str, MeteredRate]
    factor: int


@dc.dataclass(frozen=True, slots=True)
class SnapshotParts:
    """Everything a snapshot needs besides the rate map."""

    subject: Subject
    retrieved_at: dt.datetime
    effective_from: dt.datetime | None
    source_document: SourceDocument | None
    source_metadata: dict[str, str]


@dc.dataclass(frozen=True, slots=True)
class SnapshotTwin:
    """A snapshot and its equal-content counterpart in a different form."""

    base: PricingSnapshot
    equivalent: PricingSnapshot
    scale_factor: int
    offset_minutes: int


@st.composite
def subject(draw: st.DrawFn) -> Subject:
    """Draw the identity fields shared by every snapshot variant."""
    return Subject(
        service_kind=draw(st.sampled_from(PricedService)),
        source_kind=draw(st.sampled_from(PricingSourceKind)),
        currency=CurrencyCode(draw(st.sampled_from(CURRENCIES))),
        provider_name=draw(NAMES),
        model=draw(NAMES),
        operation=draw(NAMES),
    )


@st.composite
def authored_rates(draw: st.DrawFn) -> AuthoredRates:
    """Draw one rate map authored at two different integer scales."""
    factor = draw(st.sampled_from(SCALE_FACTORS))
    metrics = draw(
        st.lists(
            st.sampled_from(tuple(METRIC_UNITS)),
            min_size=2,
            max_size=4,
            unique=True,
        )
    )
    authored = {
        metric: (
            draw(st.integers(min_value=0, max_value=500_000)),
            draw(st.integers(min_value=1, max_value=1_000_000)),
        )
        for metric in metrics
    }
    base = {
        metric: MeteredRate.reduced(amount, per_units, METRIC_UNITS[metric])
        for metric, (amount, per_units) in authored.items()
    }
    scaled = {
        metric: MeteredRate.reduced(
            amount * factor,
            per_units * factor,
            METRIC_UNITS[metric],
        )
        for metric, (amount, per_units) in authored.items()
    }
    return AuthoredRates(base=base, scaled=scaled, factor=factor)


@st.composite
def provenance(
    draw: st.DrawFn,
    source_kind: st.SearchStrategy[PricingSourceKind],
    require_document: st.SearchStrategy[bool],
) -> tuple[SourceDocument | None, dict[str, str]]:
    """Draw provenance, honouring the source kind's document rule."""
    kind = draw(source_kind)
    must_have_document = (
        draw(require_document) or kind is PricingSourceKind.SLA4OAI_PLAN
    )
    has_document = must_have_document or draw(st.booleans())
    document = draw(SOURCE_DOCUMENTS) if has_document else None
    return document, draw(METADATA)


@st.composite
def instants(draw: st.DrawFn) -> tuple[dt.datetime, dt.datetime | None, int]:
    """Draw a retrieved instant, optional effective instant, and fixed offset."""
    retrieved_at = draw(AWARE_INSTANTS)
    effective_from = draw(st.one_of(st.none(), AWARE_INSTANTS))
    offset_minutes = draw(
        st.one_of(st.just(0), st.integers(-720, -1), st.integers(1, 840))
    )
    return retrieved_at, effective_from, offset_minutes


def build_snapshot(
    parts: SnapshotParts,
    rates: cabc.Mapping[str, MeteredRate],
) -> PricingSnapshot:
    """Assemble a snapshot from its identity fields and incidental form."""
    subject_fields = parts.subject
    return PricingSnapshot(
        service_kind=subject_fields.service_kind,
        provider_name=subject_fields.provider_name,
        model=subject_fields.model,
        operation=subject_fields.operation,
        source_kind=subject_fields.source_kind,
        currency=subject_fields.currency,
        rates=rates,
        retrieved_at=parts.retrieved_at,
        effective_from=parts.effective_from,
        source_document=parts.source_document,
        source_metadata=parts.source_metadata,
    )


def _equivalent_parts(parts: SnapshotParts, offset_minutes: int) -> SnapshotParts:
    """Return the same content with permuted metadata and a shifted instant."""
    zone = dt.timezone(dt.timedelta(minutes=offset_minutes))
    return dc.replace(
        parts,
        retrieved_at=parts.retrieved_at.astimezone(zone),
        effective_from=(
            None
            if parts.effective_from is None
            else parts.effective_from.astimezone(zone)
        ),
        source_metadata=dict(reversed(tuple(parts.source_metadata.items()))),
    )


def rebuild(snapshot: PricingSnapshot, **changes: object) -> PricingSnapshot:
    """Return the snapshot with the named fields replaced and rehashed."""
    return dc.replace(snapshot, **changes)


@st.composite
def snapshot_twin(
    draw: st.DrawFn,
    require_document: st.SearchStrategy[bool],
) -> SnapshotTwin:
    """Draw a snapshot and an equal-content snapshot in a different form."""
    subject_fields = draw(subject())
    rates = draw(authored_rates())
    document, metadata = draw(
        provenance(st.just(value=subject_fields.source_kind), require_document)
    )
    retrieved_at, effective_from, offset_minutes = draw(instants())
    parts = SnapshotParts(
        subject=subject_fields,
        retrieved_at=retrieved_at,
        effective_from=effective_from,
        source_document=document,
        source_metadata=metadata,
    )
    return SnapshotTwin(
        base=build_snapshot(parts, rates.base),
        equivalent=build_snapshot(
            _equivalent_parts(parts, offset_minutes),
            dict(reversed(tuple(rates.scaled.items()))),
        ),
        scale_factor=rates.factor,
        offset_minutes=offset_minutes,
    )


@st.composite
def sensitivity_snapshot(draw: st.DrawFn) -> PricingSnapshot:
    """Draw a snapshot that always carries a source document."""
    return draw(snapshot_twin(st.just(value=True))).base
