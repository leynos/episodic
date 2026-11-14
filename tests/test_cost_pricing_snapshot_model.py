"""Tests for the schema-version-1 pricing snapshot domain model."""

import datetime as dt

import pytest

from episodic.cost.pricing_snapshot import (
    MeteredRate,
    PricedService,
    PricingSnapshot,
    PricingSubject,
    SourceDocument,
    UsageUnit,
)
from episodic.cost.primitives import CurrencyCode, PricingSourceKind

_RETRIEVED_AT = dt.datetime(2026, 5, 1, tzinfo=dt.UTC)
_INPUT_RATE = MeteredRate.reduced(15, 1_000_000, UsageUnit.TOKEN)


class _OffsetlessTz(dt.tzinfo):
    """A zone that reports no UTC offset, leaving its instants naive."""

    # pylint: disable-next=useless-return  # The override must report no offset.
    def utcoffset(self, instant: dt.datetime | None) -> dt.timedelta | None:
        """Report no offset so the datetime behaves as naive."""
        del instant
        return None


def _snapshot(**overrides: object) -> PricingSnapshot:
    """Build a valid provider-rate-card snapshot with optional overrides."""
    values: dict[str, object] = {
        "service_kind": PricedService.LLM,
        "provider_name": "openai",
        "model": "gpt-4o-mini",
        "operation": "chat_completions",
        "source_kind": PricingSourceKind.PROVIDER_RATE_CARD,
        "currency": CurrencyCode("USD"),
        "rates": {"input_tokens": _INPUT_RATE},
        "retrieved_at": _RETRIEVED_AT,
    }
    values.update(overrides)
    return PricingSnapshot(**values)  # ty: ignore[invalid-argument-type]  # Overrides vary one field per case.


def test_snapshot_derives_content_hash_and_subject() -> None:
    """A valid snapshot exposes its content hash and priced subject."""
    snapshot = _snapshot(effective_from=dt.datetime(2026, 5, 1, tzinfo=dt.UTC))

    assert snapshot.content_hash.startswith("sha256:"), (
        "the content hash must use the sha256 scheme"
    )
    assert len(snapshot.content_hash) == len("sha256:") + 64, (
        "the content hash must carry a full hexadecimal digest"
    )
    assert snapshot.subject == PricingSubject(
        service_kind=PricedService.LLM,
        provider_name="openai",
        model="gpt-4o-mini",
        operation="chat_completions",
    ), "the subject must be built from the snapshot's identity fields"


def test_snapshot_freezes_caller_mappings() -> None:
    """Later mutation of the caller's dictionaries cannot change a snapshot."""
    rates = {"input_tokens": _INPUT_RATE}
    metadata = {"source_url": "https://example.test/pricing"}
    snapshot = _snapshot(rates=rates, source_metadata=metadata)
    before = snapshot.content_hash

    rates["output_tokens"] = MeteredRate.reduced(60, 1_000_000, UsageUnit.TOKEN)
    metadata["source_url"] = "https://example.test/changed"

    assert snapshot.content_hash == before, (
        "mutating the caller's mappings must not change the hash"
    )
    assert set(snapshot.rates) == {"input_tokens"}, (
        "the snapshot must keep its own copy of the rates"
    )
    assert snapshot.source_metadata["source_url"] == "https://example.test/pricing", (
        "the snapshot must keep its own copy of the metadata"
    )
    with pytest.raises(TypeError):
        snapshot.rates["output_tokens"] = _INPUT_RATE  # ty: ignore[invalid-assignment]  # Mutation is the behaviour under test.


@pytest.mark.parametrize("field", ["provider_name", "model", "operation"])
@pytest.mark.parametrize("value", ["", "   "])
def test_blank_identity_fields_are_rejected(field: str, value: str) -> None:
    """Provider, model, and operation must not be blank."""
    with pytest.raises(ValueError, match=field):
        _snapshot(**{field: value})


@pytest.mark.parametrize("code", ["usd", "ÉÉÉ", "US1"])
def test_invalid_currency_is_rejected(code: str) -> None:
    """Currency codes must be three uppercase ASCII letters."""
    with pytest.raises(ValueError, match="currency"):
        _snapshot(currency=CurrencyCode(code))


def test_naive_retrieved_at_is_rejected() -> None:
    """Instants must carry a timezone."""
    with pytest.raises(ValueError, match="retrieved_at"):
        # The naive instant is the input under test.
        _snapshot(retrieved_at=dt.datetime(2026, 5, 1))  # ruff: ignore[call-datetime-without-tzinfo]


def test_naive_effective_from_is_rejected() -> None:
    """An effective instant must carry a timezone when set."""
    with pytest.raises(ValueError, match="effective_from"):
        # The naive instant is the input under test.
        _snapshot(effective_from=dt.datetime(2026, 5, 1))  # ruff: ignore[call-datetime-without-tzinfo]


@pytest.mark.parametrize("metric", ["Input", "input-tokens", "1input", ""])
def test_invalid_metric_names_are_rejected(metric: str) -> None:
    """Metric names are identifiers so canonical keys stay predictable."""
    with pytest.raises(ValueError, match="rate metric"):
        _snapshot(rates={metric: _INPUT_RATE})


@pytest.mark.parametrize(
    ("metric", "required_unit"),
    [
        ("input_tokens", UsageUnit.TOKEN),
        ("input_characters", UsageUnit.CHARACTER),
        ("output_audio_milliseconds", UsageUnit.MILLISECOND),
        ("requests", UsageUnit.REQUEST),
    ],
)
def test_known_metric_requires_its_own_unit(
    metric: str, required_unit: UsageUnit
) -> None:
    """A known metric in another unit would price a different quantity."""
    wrong_unit = next(unit for unit in UsageUnit if unit is not required_unit)
    with pytest.raises(ValueError, match=f"denominated in {required_unit.value!r}"):
        _snapshot(rates={metric: MeteredRate.reduced(5, 1_000, wrong_unit)})


def test_boolean_schema_version_is_rejected() -> None:
    """``True`` equals 1, but the canonical form needs the integer version."""
    with pytest.raises(ValueError, match="schema_version"):
        _snapshot(schema_version=True)


def test_instant_without_a_utc_offset_is_rejected() -> None:
    """A zone that reports no offset would hash differently on each host."""
    offsetless = dt.datetime(2026, 5, 1, tzinfo=_OffsetlessTz())
    with pytest.raises(ValueError, match="timezone-aware"):
        _snapshot(retrieved_at=offsetless)


def test_unknown_metric_accepts_any_unit() -> None:
    """Metric names stay open, so an undocumented name keeps its stated unit."""
    rate = MeteredRate.reduced(5, 1_000, UsageUnit.CHARACTER)
    snapshot = _snapshot(rates={"glyphs_rendered": rate})
    assert snapshot.rates["glyphs_rendered"] is rate, (
        "an undocumented metric must keep the unit its card states"
    )


def test_invalid_source_metadata_key_is_rejected() -> None:
    """Source metadata keys are identifiers, not free-form labels."""
    with pytest.raises(ValueError, match="source_metadata key"):
        _snapshot(source_metadata={"Source URL": "https://example.test"})


def test_provider_rate_card_requires_a_rate() -> None:
    """A rate card with no rates cannot price anything."""
    with pytest.raises(ValueError, match="at least one metric"):
        _snapshot(rates={})


def test_sla_plan_requires_a_source_document() -> None:
    """Service-level agreement snapshots must carry their source document."""
    with pytest.raises(ValueError, match="source_document"):
        _snapshot(source_kind=PricingSourceKind.SLA4OAI_PLAN)


def test_sla_plan_accepts_a_source_document() -> None:
    """A service-level agreement snapshot is valid with its document."""
    snapshot = _snapshot(
        source_kind=PricingSourceKind.SLA4OAI_PLAN,
        source_document=SourceDocument(media_type="application/yaml", content="plan"),
    )

    assert snapshot.source_document is not None, "the source document must be retained"
    assert snapshot.source_document.sha256.startswith("sha256:"), (
        "the source document must be digested"
    )


@pytest.mark.parametrize("version", [0, 2, 99])
def test_unknown_schema_version_is_rejected(version: int) -> None:
    """Only schema version 1 is understood by this release."""
    with pytest.raises(ValueError, match="schema_version"):
        _snapshot(schema_version=version)


def test_equal_content_shares_a_hash() -> None:
    """Snapshots built from equal content are the same identity."""
    assert _snapshot().content_hash == _snapshot().content_hash, (
        "equal content must produce one identity"
    )


def test_changing_a_hashed_field_changes_the_hash() -> None:
    """Every hashed field participates in the identity."""
    baseline = _snapshot().content_hash
    changed = _snapshot(
        rates={
            "input_tokens": _INPUT_RATE,
            "output_tokens": MeteredRate.reduced(60, 1_000_000, UsageUnit.TOKEN),
        },
    ).content_hash

    assert changed != baseline, "changing a hashed field must change the identity"


def test_instant_offsets_hash_as_utc() -> None:
    """The same instant in another offset produces the same hash."""
    other_offset = dt.timezone(dt.timedelta(hours=2))
    shifted = dt.datetime(2026, 5, 1, 2, tzinfo=other_offset)

    assert _snapshot(retrieved_at=shifted).content_hash == _snapshot().content_hash, (
        "an equal instant in another offset must hash identically"
    )


@pytest.mark.parametrize(
    ("amount", "per_units", "expected"),
    [
        (15, 1_000_000, (3, 200_000)),
        (0, 1_000_000, (0, 1)),
        (60, 1_000_000, (3, 50_000)),
        (7, 1, (7, 1)),
    ],
)
def test_metered_rate_reduces_to_lowest_terms(
    amount: int, per_units: int, expected: tuple[int, int]
) -> None:
    """Rates normalize so equal prices share one representation."""
    rate = MeteredRate.reduced(amount, per_units, UsageUnit.TOKEN)

    assert (rate.amount_minor, rate.per_units) == expected, (
        "the rate must be reduced to lowest terms"
    )


def test_metered_rate_rejects_non_reduced_values() -> None:
    """Constructing a non-canonical fraction directly is a defect."""
    with pytest.raises(ValueError, match="lowest terms"):
        MeteredRate(15, 1_000_000, UsageUnit.TOKEN)


@pytest.mark.parametrize("per_units", [0, -1])
def test_metered_rate_rejects_invalid_denominator(per_units: int) -> None:
    """A rate must divide by a positive number of units."""
    with pytest.raises(ValueError, match="per_units"):
        MeteredRate.reduced(1, per_units, UsageUnit.TOKEN)


def test_metered_rate_rejects_negative_amount() -> None:
    """Prices are non-negative."""
    with pytest.raises(ValueError, match="amount_minor"):
        MeteredRate.reduced(-1, 1_000_000, UsageUnit.TOKEN)


def test_source_document_rejects_oversized_content() -> None:
    """The stored document must stay within the column budget."""
    with pytest.raises(ValueError, match="262144"):
        SourceDocument(media_type="text/plain", content="x" * 262_145)


def test_source_document_digest_covers_utf8_bytes() -> None:
    """The digest is computed over the UTF-8 encoding of the content."""
    document = SourceDocument(media_type="text/plain", content="café")

    assert document.sha256 == (
        "sha256:850f7dc43910ff890f8879c0ed26fe697c93a067ad93a7d50f466a7028a9bf4e"
    ), "the digest must cover the UTF-8 bytes, not the code points"
