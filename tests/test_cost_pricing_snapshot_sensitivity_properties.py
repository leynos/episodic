"""Property tests for pricing snapshot hash sensitivity.

Satisfies ExecPlan obligation `INV-HASH-SENS`: changing any single hashed field
changes the content hash. The mutation table is keyed by every name in
`PRICING_SNAPSHOT_V1_FIELDS`, and the companion coverage test fails if a field
is added without bumping the schema. A seeded fault that drops
`source_metadata` from the canonical form is shown to hide a metadata change.
"""

import collections.abc as cabc
import dataclasses as dc
import datetime as dt
import functools

import hypothesis.strategies as st
import pytest
from hypothesis import given, settings

from episodic.cost.pricing_snapshot import (
    MeteredRate,
    PricedService,
    PricingSnapshot,
    SourceDocument,
    UsageUnit,
)
from episodic.cost.pricing_snapshot_hash import (
    PRICING_SNAPSHOT_V1_FIELDS,
    canonical_pricing_document,
)
from episodic.cost.primitives import CurrencyCode, PricingSourceKind
from episodic.json_canonicalization import canonical_json_bytes
from tests.pricing_snapshot_hash_strategies import (
    AWARE_INSTANTS,
    CURRENCIES,
    METADATA,
    NAMES,
    SOURCE_DOCUMENTS,
    rebuild,
    sensitivity_snapshot,
)

type MutationBuilder = cabc.Callable[
    [PricingSnapshot], st.SearchStrategy[PricingSnapshot]
]


def _unsupported_version_snapshot(base: PricingSnapshot) -> PricingSnapshot:
    """Return an object claiming a version with no registered encoder."""
    # The dataclass rejects any version but one, so build a valid snapshot and
    # overwrite the slot to reach the encoder lookup a future version would
    # rely on. Keeping every other slot populated keeps the object hashable,
    # which Hypothesis needs when labelling the strategy element.
    snapshot = rebuild(base)
    object.__setattr__(snapshot, "schema_version", base.schema_version + 1)
    return snapshot


def _mutate_name(
    base: PricingSnapshot,
    *,
    field: str,
) -> st.SearchStrategy[PricingSnapshot]:
    """Draw a snapshot differing only in one non-blank name field."""
    return NAMES.filter(lambda candidate: candidate != getattr(base, field)).map(
        lambda candidate: rebuild(base, **{field: candidate})
    )


def _mutate_currency(base: PricingSnapshot) -> st.SearchStrategy[PricingSnapshot]:
    """Draw a snapshot differing only in its currency."""
    alternatives = [code for code in CURRENCIES if code != str(base.currency)]
    return st.sampled_from(alternatives).map(
        lambda code: rebuild(base, currency=CurrencyCode(code))
    )


def _mutate_effective_from(
    base: PricingSnapshot,
) -> st.SearchStrategy[PricingSnapshot]:
    """Draw a snapshot differing only in its effective instant."""
    return AWARE_INSTANTS.filter(lambda instant: instant != base.effective_from).map(
        lambda instant: rebuild(base, effective_from=instant)
    )


def _mutate_rates(base: PricingSnapshot) -> st.SearchStrategy[PricingSnapshot]:
    """Draw a snapshot differing only in one rate value."""
    metric = min(base.rates)
    current = base.rates[metric]

    def _different(amount: int) -> bool:
        """Reject amounts that reduce to the stored rate."""
        return MeteredRate.reduced(amount, current.per_units, current.unit) != current

    return (
        st
        .integers(min_value=0, max_value=1_000_000)
        .filter(_different)
        .map(
            lambda amount: rebuild(
                base,
                rates={
                    **base.rates,
                    metric: MeteredRate.reduced(
                        amount, current.per_units, current.unit
                    ),
                },
            )
        )
    )


def _mutate_retrieved_at(
    base: PricingSnapshot,
) -> st.SearchStrategy[PricingSnapshot]:
    """Draw a snapshot differing only in its retrieved instant."""
    return AWARE_INSTANTS.filter(lambda instant: instant != base.retrieved_at).map(
        lambda instant: rebuild(base, retrieved_at=instant)
    )


def _mutate_schema_version(
    base: PricingSnapshot,
) -> st.SearchStrategy[PricingSnapshot]:
    """Draw an object claiming an unregistered schema version."""
    return st.just(value=_unsupported_version_snapshot(base))


def _mutate_service_kind(
    base: PricingSnapshot,
) -> st.SearchStrategy[PricingSnapshot]:
    """Draw a snapshot differing only in its service kind."""
    alternatives = [kind for kind in PricedService if kind is not base.service_kind]
    return st.sampled_from(alternatives).map(
        lambda kind: rebuild(base, service_kind=kind)
    )


def _mutate_source_document(
    base: PricingSnapshot,
) -> st.SearchStrategy[PricingSnapshot]:
    """Draw a snapshot differing only in its source document."""
    return SOURCE_DOCUMENTS.filter(
        lambda document: document != base.source_document
    ).map(lambda document: rebuild(base, source_document=document))


def _mutate_source_kind(base: PricingSnapshot) -> st.SearchStrategy[PricingSnapshot]:
    """Draw a snapshot differing only in its pricing source kind."""
    other = (
        PricingSourceKind.SLA4OAI_PLAN
        if base.source_kind is PricingSourceKind.PROVIDER_RATE_CARD
        else PricingSourceKind.PROVIDER_RATE_CARD
    )
    return st.just(value=rebuild(base, source_kind=other))


def _mutate_source_metadata(
    base: PricingSnapshot,
) -> st.SearchStrategy[PricingSnapshot]:
    """Draw a snapshot differing only in its source metadata."""
    return METADATA.filter(lambda metadata: metadata != dict(base.source_metadata)).map(
        lambda metadata: rebuild(base, source_metadata=metadata)
    )


_MUTATION_BUILDERS: dict[str, MutationBuilder] = {
    "currency": _mutate_currency,
    "effective_from": _mutate_effective_from,
    "model": functools.partial(_mutate_name, field="model"),
    "operation": functools.partial(_mutate_name, field="operation"),
    "provider_name": functools.partial(_mutate_name, field="provider_name"),
    "rates": _mutate_rates,
    "retrieved_at": _mutate_retrieved_at,
    "schema_version": _mutate_schema_version,
    "service_kind": _mutate_service_kind,
    "source_document": _mutate_source_document,
    "source_kind": _mutate_source_kind,
    "source_metadata": _mutate_source_metadata,
}


@st.composite
def _mutated_snapshot(
    draw: st.DrawFn,
) -> tuple[PricingSnapshot, PricingSnapshot, str]:
    """Draw a base snapshot and a mutation of one hashed field."""
    base = draw(sensitivity_snapshot())
    field = draw(st.sampled_from(PRICING_SNAPSHOT_V1_FIELDS))
    return base, draw(_MUTATION_BUILDERS[field](base)), field


@st.composite
def _metadata_fault_case(
    draw: st.DrawFn,
) -> tuple[PricingSnapshot, PricingSnapshot]:
    """Draw a base snapshot and a mutation of only its source metadata."""
    base = draw(sensitivity_snapshot())
    return base, draw(_mutate_source_metadata(base))


def _document_without_source_metadata(
    snapshot: PricingSnapshot,
) -> dict[str, object]:
    """Re-encode the canonical document with source_metadata dropped."""
    document = canonical_pricing_document(snapshot)
    del document["source_metadata"]
    return document


def _example_snapshot() -> PricingSnapshot:
    """Build one fully populated snapshot for structural assertions."""
    return PricingSnapshot(
        service_kind=PricedService.LLM,
        provider_name="openai",
        model="gpt-4o-mini",
        operation="chat_completions",
        source_kind=PricingSourceKind.SLA4OAI_PLAN,
        currency=CurrencyCode("USD"),
        rates={
            "input_tokens": MeteredRate.reduced(15, 1_000_000, UsageUnit.TOKEN),
            "output_tokens": MeteredRate.reduced(60, 1_000_000, UsageUnit.TOKEN),
        },
        retrieved_at=dt.datetime(
            2026,
            5,
            1,
            2,
            30,
            tzinfo=dt.timezone(dt.timedelta(hours=2)),
        ),
        effective_from=dt.datetime(2026, 5, 1, tzinfo=dt.UTC),
        source_document=SourceDocument(media_type="application/yaml", content="plan"),
        source_metadata={"source_url": "https://example.test/pricing"},
    )


@given(case=_mutated_snapshot())
@settings(max_examples=150, deadline=None)
def test_changing_one_hashed_field_changes_the_hash(
    case: tuple[PricingSnapshot, PricingSnapshot, str],
) -> None:
    """INV-HASH-SENS: any single hashed field changes the content hash."""
    base, mutated, field = case
    if field == "schema_version":
        with pytest.raises(ValueError, match="no canonical encoder"):
            canonical_pricing_document(mutated)
        return
    assert mutated.content_hash != base.content_hash, (
        f"changing {field} must change the content hash"
    )


def test_mutation_table_covers_every_v1_field() -> None:
    """INV-HASH-SENS non-vacuity: every hashed field has a mutation."""
    snapshot = _example_snapshot()
    assert tuple(_MUTATION_BUILDERS) == PRICING_SNAPSHOT_V1_FIELDS, (
        "every hashed field must have a mutation builder"
    )
    assert tuple(canonical_pricing_document(snapshot)) == (
        PRICING_SNAPSHOT_V1_FIELDS
    ), "the canonical document must emit exactly the hashed fields"
    hashed_fields = frozenset(
        field.name
        for field in dc.fields(PricingSnapshot)
        if field.name != "content_hash"
    )
    assert hashed_fields == frozenset(PRICING_SNAPSHOT_V1_FIELDS), (
        "the field tuple must cover every snapshot field but the hash"
    )


@given(case=_metadata_fault_case())
@settings(max_examples=50, deadline=None)
def test_omitting_source_metadata_breaks_sensitivity(
    case: tuple[PricingSnapshot, PricingSnapshot],
) -> None:
    """INV-HASH-SENS negative control: dropping metadata hides a change."""
    base, mutated = case
    faulted_base = _document_without_source_metadata(base)
    faulted_mutated = _document_without_source_metadata(mutated)
    assert "source_metadata" not in faulted_base, (
        "the seeded fault must drop the field before hashing"
    )
    assert dict(base.source_metadata) != dict(mutated.source_metadata), (
        "the metadata mutation must actually change the field"
    )
    assert canonical_json_bytes(faulted_base) == canonical_json_bytes(
        faulted_mutated
    ), "with the field dropped the two documents must collide"
    assert base.content_hash != mutated.content_hash, (
        "the honest hashes must still differ"
    )
