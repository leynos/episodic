"""Pinned vectors for the schema-version-1 pricing snapshot hash."""

import datetime as dt
import typing as typ

import pytest

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
    pricing_snapshot_content_hash,
)
from episodic.cost.primitives import CurrencyCode, PricingSourceKind
from episodic.json_canonicalization import canonical_json_bytes

if typ.TYPE_CHECKING:
    from syrupy.assertion import SnapshotAssertion

_CANONICAL_JSON = (
    '{"currency":"USD","effective_from":"2026-05-01T00:00:00.000000Z",'
    '"model":"gpt-4o-mini","operation":"chat_completions","provider_name":"openai",'
    '"rates":{"input_tokens":{"amount_minor":3,"per_units":200000,"unit":"token"},'
    '"output_tokens":{"amount_minor":3,"per_units":50000,"unit":"token"}},'
    '"retrieved_at":"2026-05-01T00:30:00.000000Z","schema_version":1,'
    '"service_kind":"llm","source_document":{"media_type":"application/yaml",'
    '"sha256":"sha256:c357cca0909f1a2aaf833a0d7f277925abb283937c2210525c374af9d61b9c0c"},'
    '"source_kind":"sla4oai_plan",'
    '"source_metadata":{"source_url":"https://openai.com/api/pricing/"}}'
)
_EXPECTED_HASH = (
    "sha256:912f19b822917adbaa268a6b08384fe8a101528a86733eb6ec39f43039c1e0d7"
)


def _vector_snapshot() -> PricingSnapshot:
    """Build the snapshot pinned by the ADR-024 hash vector."""
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
        source_metadata={"source_url": "https://openai.com/api/pricing/"},
        retrieved_at=dt.datetime(
            2026,
            5,
            1,
            2,
            30,
            tzinfo=dt.timezone(dt.timedelta(hours=2)),
        ),
        effective_from=dt.datetime(2026, 5, 1, tzinfo=dt.UTC),
        source_document=SourceDocument(
            media_type="application/yaml",
            content="plan: v1",
        ),
    )


def test_canonical_document_has_exactly_the_v1_fields() -> None:
    """The canonical document is the complete, closed v1 field set."""
    document = canonical_pricing_document(_vector_snapshot())

    assert tuple(sorted(document)) == tuple(sorted(PRICING_SNAPSHOT_V1_FIELDS)), (
        "the canonical document must carry exactly the v1 fields"
    )


def test_canonical_json_matches_the_pinned_vector() -> None:
    """The canonical bytes are stable across releases."""
    document = canonical_pricing_document(_vector_snapshot())

    assert canonical_json_bytes(document).decode("utf-8") == _CANONICAL_JSON, (
        "the canonical bytes must match the pinned vector"
    )


def test_content_hash_matches_the_pinned_vector() -> None:
    """The content hash is stable across releases."""
    assert pricing_snapshot_content_hash(_vector_snapshot()) == _EXPECTED_HASH, (
        "the content hash must match the pinned vector"
    )


def test_instants_always_carry_six_fractional_digits() -> None:
    """Whole-second instants still encode six fractional digits."""
    document = canonical_pricing_document(_vector_snapshot())

    assert document["retrieved_at"] == "2026-05-01T00:30:00.000000Z", (
        "the retrieved instant must encode six fractional digits in UTC"
    )
    assert document["effective_from"] == "2026-05-01T00:00:00.000000Z", (
        "the effective instant must encode six fractional digits in UTC"
    )


def test_absent_optional_fields_encode_as_null() -> None:
    """An absent effective instant and source document are explicit nulls."""
    snapshot = PricingSnapshot(
        service_kind=PricedService.LLM,
        provider_name="openai",
        model="gpt-4o-mini",
        operation="chat_completions",
        source_kind=PricingSourceKind.PROVIDER_RATE_CARD,
        currency=CurrencyCode("USD"),
        rates={"input_tokens": MeteredRate.reduced(15, 1_000_000, UsageUnit.TOKEN)},
        retrieved_at=dt.datetime(2026, 5, 1, tzinfo=dt.UTC),
    )

    document = canonical_pricing_document(snapshot)

    assert document["effective_from"] is None, (
        "an absent effective instant must encode as null"
    )
    assert document["source_document"] is None, (
        "an absent source document must encode as null"
    )


def _llm_vector() -> PricingSnapshot:
    """Build the LLM vector: non-UTC instant, no effective date, no document."""
    return PricingSnapshot(
        service_kind=PricedService.LLM,
        provider_name="openai",
        model="gpt-4o-mini",
        operation="chat_completions",
        source_kind=PricingSourceKind.PROVIDER_RATE_CARD,
        currency=CurrencyCode("USD"),
        # Authored per million; the constructor normalizes to lowest terms.
        rates={
            "input_tokens": MeteredRate.reduced(15, 1_000_000, UsageUnit.TOKEN),
            "output_tokens": MeteredRate.reduced(60, 1_000_000, UsageUnit.TOKEN),
        },
        source_metadata={"source_url": "https://openai.com/api/pricing/"},
        retrieved_at=dt.datetime(
            2026,
            5,
            1,
            2,
            30,
            tzinfo=dt.timezone(dt.timedelta(hours=2)),
        ),
    )


def _tts_vector() -> PricingSnapshot:
    """Build the TTS vector: five cents per minute of audio."""
    return PricingSnapshot(
        service_kind=PricedService.TTS,
        provider_name="openai",
        model="tts-1",
        operation="speech",
        source_kind=PricingSourceKind.PROVIDER_RATE_CARD,
        currency=CurrencyCode("USD"),
        rates={"milliseconds": MeteredRate.reduced(5, 60_000, UsageUnit.MILLISECOND)},
        source_metadata={},
        retrieved_at=dt.datetime(2026, 5, 1, tzinfo=dt.UTC),
        effective_from=dt.datetime(2026, 4, 1, tzinfo=dt.UTC),
    )


_VECTORS = {
    "llm": _llm_vector,
    "sla4oai_plan": _vector_snapshot,
    "tts": _tts_vector,
}


@pytest.mark.parametrize("name", sorted(_VECTORS))
def test_canonical_vectors_are_pinned(name: str, snapshot: SnapshotAssertion) -> None:
    """Canonical bytes and hashes are stable for the documented vectors."""
    pricing = _VECTORS[name]()
    rendered = {
        "canonical_json": canonical_json_bytes(
            canonical_pricing_document(pricing)
        ).decode("utf-8"),
        "content_hash": pricing_snapshot_content_hash(pricing),
    }

    assert rendered == snapshot, "the documented vector must stay byte-stable"
