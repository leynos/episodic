"""Schema-version-1 file catalogue loading and resolution.

Each test writes one or more YAML cards into ``tmp_path`` and loads them with
``FilePricingCatalogue`` under a frozen clock, so effective-date
selection and strict parsing are exercised without touching the shipped cards.
Run the module with ``pytest tests/test_cost_pricing_catalogue_v1.py``.
"""

import datetime as dt
import textwrap
import typing as typ

import pytest

from episodic.cost.pricing_catalogue import FilePricingCatalogue, PricingCatalogueError
from episodic.cost.pricing_snapshot import PricedService, PricingSubject

if typ.TYPE_CHECKING:
    import pathlib


_SUBJECT = PricingSubject(
    service_kind=PricedService.LLM,
    provider_name="openai",
    model="gpt-4o-mini",
    operation="chat_completions",
)


def _write(directory: pathlib.Path, name: str, body: str) -> None:
    """Write a YAML pricing card fixture."""
    (directory / name).write_text(
        textwrap.dedent(body).strip() + "\n",
        encoding="utf-8",
    )


def _card(
    *,
    effective_from: str = "2026-05-01T00:00:00Z",
    input_amount: str = "15",
    cached_amount: str = "8",
) -> str:
    """Build a schema-version-1 rate card body."""
    return f"""
    schema_version: 1
    service_kind: llm
    provider_name: openai
    model: gpt-4o-mini
    operation: chat_completions
    source_kind: provider_rate_card
    currency: USD
    rates:
      input_tokens:
        amount_minor: {input_amount}
        per_units: 1000000
        unit: token
      cached_input_tokens:
        amount_minor: {cached_amount}
        per_units: 1000000
        unit: token
    source_metadata:
      source_url: https://example.test/pricing
    retrieved_at: "2026-05-01T00:00:00Z"
    effective_from: "{effective_from}"
    """


def _catalogue(directory: pathlib.Path, now: str) -> FilePricingCatalogue:
    """Build an eagerly loaded catalogue with a frozen clock."""
    return FilePricingCatalogue(
        directory,
        now=lambda: now,
    )


def _revised_catalogue(directory: pathlib.Path) -> FilePricingCatalogue:
    """Load a card revised mid-May, so an earlier call sees the old rate."""
    _write(directory, "old.yaml", _card(input_amount="10"))
    _write(
        directory,
        "new.yaml",
        _card(effective_from="2026-05-15T00:00:00Z", input_amount="20"),
    )
    return _catalogue(directory, "2026-06-04T00:00:00Z")


@pytest.mark.asyncio
async def test_resolves_the_latest_effective_card(tmp_path: pathlib.Path) -> None:
    """The greatest effective instant not after now wins."""
    catalogue = _revised_catalogue(tmp_path)

    snapshot = await catalogue.resolve(_SUBJECT)

    rate = snapshot.rates["input_tokens"]
    assert (rate.amount_minor, rate.per_units) == (1, 50_000), (
        f"20/1_000_000 must reduce to 1/50_000, got {rate!r}"
    )


@pytest.mark.asyncio
async def test_resolution_uses_the_captured_call_time(tmp_path: pathlib.Path) -> None:
    """A call captured before a rate change keeps the earlier card."""
    catalogue = _revised_catalogue(tmp_path)

    snapshot = await catalogue.resolve(_SUBJECT, at="2026-05-10T00:00:00Z")

    rate = snapshot.rates["input_tokens"]
    assert (rate.amount_minor, rate.per_units) == (1, 100_000), (
        "a call captured before the new card must keep the earlier rate"
    )


@pytest.mark.asyncio
async def test_crlf_plan_document_is_stored_verbatim(
    tmp_path: pathlib.Path,
) -> None:
    """A CRLF plan keeps its line endings in the retained source document."""
    body = textwrap.dedent(_card().replace("provider_rate_card", "sla4oai_plan"))
    (tmp_path / "plan.yaml").write_bytes(
        (body.strip() + "\n").replace("\n", "\r\n").encode("utf-8")
    )
    catalogue = _catalogue(tmp_path, "2026-06-04T00:00:00Z")

    snapshot = await catalogue.resolve(_SUBJECT)

    document = snapshot.source_document
    assert document is not None, "an SLA4OAI card must retain its document"
    assert "\r\n" in document.content, "line endings must survive the read"


@pytest.mark.asyncio
async def test_a_card_keeps_applying_in_a_later_month(
    tmp_path: pathlib.Path,
) -> None:
    """A May card still prices June usage; billing periods left the snapshot."""
    _write(tmp_path, "may.yaml", _card())
    catalogue = _catalogue(tmp_path, "2026-06-04T00:00:00Z")

    snapshot = await catalogue.resolve(_SUBJECT)

    assert snapshot.effective_from == dt.datetime(2026, 5, 1, tzinfo=dt.UTC), (
        "the May card must still be selected in June"
    )


@pytest.mark.asyncio
async def test_future_dated_card_is_ignored(tmp_path: pathlib.Path) -> None:
    """A card that is not yet effective cannot price a call."""
    _write(tmp_path, "future.yaml", _card(effective_from="2026-07-01T00:00:00Z"))
    catalogue = _catalogue(tmp_path, "2026-06-04T00:00:00Z")

    with pytest.raises(LookupError, match="No pricing snapshot"):
        await catalogue.resolve(_SUBJECT)


def test_duplicate_subject_and_effective_instant_is_rejected(
    tmp_path: pathlib.Path,
) -> None:
    """Two cards for one subject and instant are ambiguous."""
    _write(tmp_path, "a.yaml", _card(input_amount="10"))
    _write(tmp_path, "b.yaml", _card(input_amount="20"))

    with pytest.raises(PricingCatalogueError, match=r"a\.yaml|b\.yaml"):
        _catalogue(tmp_path, "2026-06-04T00:00:00Z")


def test_legacy_document_format_is_rejected(tmp_path: pathlib.Path) -> None:
    """A pre-v1 card must fail loudly rather than be silently misread."""
    _write(
        tmp_path,
        "legacy.yaml",
        """
        pricing_snapshot_id: 018f15f8-8c12-7c3a-9e9f-9f8f8f8f8f8f
        provider_name: openai
        model: gpt-4o-mini
        operation: chat_completions
        source_kind: provider_rate_card
        currency: USD
        billing_period_key: "2026-06"
        rates_minor_per_metric:
          input_tokens: 100
        retrieved_at: "2026-05-01T00:00:00Z"
        """,
    )

    with pytest.raises(
        PricingCatalogueError,
        match=r"legacy\.yaml.*schema version 1.*users-guide",
    ):
        _catalogue(tmp_path, "2026-06-04T00:00:00Z")


@pytest.mark.asyncio
async def test_decimal_string_amounts_convert_exactly(
    tmp_path: pathlib.Path,
) -> None:
    """A decimal string expresses a fractional minor-unit price exactly."""
    _write(tmp_path, "card.yaml", _card(cached_amount='"7.5"'))
    catalogue = _catalogue(tmp_path, "2026-06-04T00:00:00Z")

    snapshot = await catalogue.resolve(_SUBJECT)

    cached = snapshot.rates["cached_input_tokens"]
    assert (cached.amount_minor, cached.per_units) == (3, 400_000), (
        f"7.5/1_000_000 must reduce to 3/400_000, got {cached!r}"
    )


@pytest.mark.asyncio
async def test_missing_directory_is_an_empty_catalogue(
    tmp_path: pathlib.Path,
) -> None:
    """A deployment without cards loads, then fails to resolve."""
    catalogue = _catalogue(tmp_path / "absent", "2026-06-04T00:00:00Z")

    with pytest.raises(LookupError, match="No pricing snapshot"):
        await catalogue.resolve(_SUBJECT)
