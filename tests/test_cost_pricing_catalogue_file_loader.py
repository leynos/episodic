"""Strictness tests for schema-version-1 pricing-card parsing."""

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


def _write_card(directory: pathlib.Path, body: str, name: str = "openai.yaml") -> None:
    """Write one YAML pricing card fixture."""
    (directory / name).write_text(
        textwrap.dedent(body).strip() + "\n",
        encoding="utf-8",
    )


def _write_bytes(directory: pathlib.Path, body: bytes) -> pathlib.Path:
    """Write one raw pricing-card fixture and return its path."""
    path = directory / "broken.yaml"
    path.write_bytes(body)
    return path


def _card(
    *,
    effective_from: str = '"2026-06-01T00:00:00Z"',
    extra: str = "",
) -> str:
    """Build a minimal schema-version-1 rate card body."""
    return f"""
    schema_version: 1
    service_kind: llm
    provider_name: openai
    model: gpt-4o-mini
    operation: chat_completions
    source_kind: provider_rate_card
    currency: USD
    rates:
      input_tokens: {{amount_minor: 15, per_units: 1000000, unit: token}}
    source_metadata:
      source_url: https://example.test/pricing
    retrieved_at: "2026-06-01T00:00:00Z"
    effective_from: {effective_from}
    {extra}
    """


@pytest.mark.asyncio
async def test_loader_propagates_the_effective_instant(
    tmp_path: pathlib.Path,
) -> None:
    """The parsed effective date reaches the domain snapshot as an aware instant."""
    _write_card(tmp_path, _card())

    snapshot = await FilePricingCatalogue(tmp_path).resolve(_SUBJECT)

    assert snapshot.effective_from == dt.datetime(2026, 6, 1, tzinfo=dt.UTC), (
        f"expected the parsed effective date, got {snapshot.effective_from!r}"
    )
    assert snapshot.effective_from is not None, (
        "the loaded card declares an effective date"
    )
    assert snapshot.effective_from.tzinfo is not None, (
        "the loaded effective date must be timezone-aware"
    )


@pytest.mark.asyncio
async def test_resolve_reads_only_the_cards_loaded_at_construction(
    tmp_path: pathlib.Path,
) -> None:
    """A resolution must not re-read the directory the catalogue was built from."""
    _write_card(tmp_path, _card())
    catalogue = FilePricingCatalogue(tmp_path, now=lambda: "2026-06-15T00:00:00Z")
    _write_card(tmp_path, _card().replace("amount_minor: 15", "amount_minor: 99"))

    snapshot = await catalogue.resolve(_SUBJECT)

    rate = snapshot.rates["input_tokens"]
    assert (rate.amount_minor, rate.per_units) == (3, 200_000), (
        "a resolution must use the 15 per million card loaded at construction, "
        f"not the edited file on disk; got {rate!r}"
    )


@pytest.mark.asyncio
async def test_decimal_amount_reduces_before_the_integer_limit_is_checked(
    tmp_path: pathlib.Path,
) -> None:
    """A reducible decimal rate is accepted even when its raw parts overflow."""
    _write_card(
        tmp_path,
        _card().replace(
            "amount_minor: 15, per_units: 1000000",
            'amount_minor: "7.5", per_units: 5000000000000000',
        ),
    )
    catalogue = FilePricingCatalogue(tmp_path, now=lambda: "2026-06-15T00:00:00Z")

    snapshot = await catalogue.resolve(_SUBJECT)

    rate = snapshot.rates["input_tokens"]
    assert (rate.amount_minor, rate.per_units) == (3, 2_000_000_000_000_000), (
        f"7.5 per 5e15 units must reduce to 3 per 2e15, got {rate!r}"
    )


@pytest.mark.parametrize(
    ("amount_minor", "per_units"),
    [
        pytest.param("0", "0", id="zero-amount-zero-denominator"),
        pytest.param("15", "0", id="priced-amount-zero-denominator"),
        pytest.param("15", "-1000000", id="negative-denominator"),
    ],
)
def test_loader_rejects_a_non_positive_denominator(
    tmp_path: pathlib.Path,
    amount_minor: str,
    per_units: str,
) -> None:
    """A non-positive denominator is a card error naming the file, not a crash."""
    _write_card(
        tmp_path,
        _card().replace(
            "amount_minor: 15, per_units: 1000000",
            f"amount_minor: {amount_minor}, per_units: {per_units}",
        ),
    )

    with pytest.raises(
        PricingCatalogueError,
        match=r"openai\.yaml: rate 'input_tokens' per_units must be positive",
    ):
        FilePricingCatalogue(tmp_path)


@pytest.mark.asyncio
async def test_zero_cost_rate_with_a_positive_denominator_is_accepted(
    tmp_path: pathlib.Path,
) -> None:
    """A free metric is a price, so it must still load and reduce to zero."""
    _write_card(
        tmp_path,
        _card().replace("amount_minor: 15", "amount_minor: 0"),
    )
    catalogue = FilePricingCatalogue(tmp_path, now=lambda: "2026-06-15T00:00:00Z")

    snapshot = await catalogue.resolve(_SUBJECT)

    rate = snapshot.rates["input_tokens"]
    assert (rate.amount_minor, rate.per_units) == (0, 1), (
        f"a zero amount must reduce to 0 per 1, got {rate!r}"
    )


@pytest.mark.parametrize("invalid_value", ["false", "0", "[]", "{}"])
def test_loader_rejects_a_non_string_effective_from(
    tmp_path: pathlib.Path,
    invalid_value: str,
) -> None:
    """Present but non-string effective dates must fail loading."""
    _write_card(tmp_path, _card(effective_from=invalid_value))

    with pytest.raises(PricingCatalogueError, match="effective_from"):
        FilePricingCatalogue(tmp_path)


@pytest.mark.parametrize(
    ("body", "match"),
    [
        pytest.param(
            _card(extra="unexpected_field: 1"),
            "unexpected_field",
            id="unknown-field",
        ),
        pytest.param(
            _card().replace("source_url:", '"Source URL":'),
            "source_metadata",
            id="non-identifier-metadata-key",
        ),
        pytest.param(
            _card().replace(
                "    rates:\n",
                "    rates:\n"
                "      output_tokens: "
                "{amount_minor: 3, per_units: 50000, unit: token}\n"
                "    rates:\n",
                1,
            ),
            "duplicate key",
            id="duplicate-key",
        ),
        pytest.param(
            _card().replace(
                "    rates:\n",
                "    ? [a, b]\n    : 1\n    rates:\n",
                1,
            ),
            "unhashable key",
            id="unhashable-key",
        ),
        pytest.param(
            _card().replace("unit: token", "unit: kilogram"),
            "kilogram",
            id="unknown-rate-unit",
        ),
        pytest.param(
            _card().replace("unit: token", "unit: token, rounding: up"),
            "unknown fields in rate",
            id="unknown-rate-field",
        ),
        pytest.param(
            _card().replace("amount_minor: 15", 'amount_minor: "1e999999999"'),
            "exponent is out of range",
            id="huge-positive-exponent",
        ),
        pytest.param(
            _card().replace("amount_minor: 15", 'amount_minor: "1e-999999999"'),
            "exponent is out of range",
            id="huge-negative-exponent",
        ),
        pytest.param(
            _card().replace(
                "    rates:\n"
                "      input_tokens: "
                "{amount_minor: 15, per_units: 1000000, unit: token}\n",
                "",
            ),
            "missing required fields: rates",
            id="missing-required-field",
        ),
    ],
)
def test_loader_rejects_an_invalid_card(
    tmp_path: pathlib.Path,
    body: str,
    match: str,
) -> None:
    """A card outside the schema version fails with a message naming the problem."""
    _write_card(tmp_path, body)

    with pytest.raises(PricingCatalogueError, match=match):
        FilePricingCatalogue(tmp_path)


def test_loader_reports_undecodable_bytes_with_the_file_name(
    tmp_path: pathlib.Path,
) -> None:
    """Invalid UTF-8 surfaces as a catalogue error that names the card."""
    path = _write_bytes(tmp_path, b"\xff\xfe")

    with pytest.raises(PricingCatalogueError, match=rf"{path.name}: cannot read card"):
        FilePricingCatalogue(tmp_path)


def test_loader_reports_unreadable_cards_with_the_file_name(
    tmp_path: pathlib.Path,
) -> None:
    """A card path that cannot be read surfaces as a catalogue error."""
    (tmp_path / "broken.yaml").mkdir()

    with pytest.raises(PricingCatalogueError, match=r"cannot read card.*broken\.yaml"):
        FilePricingCatalogue(tmp_path)


def test_loader_reports_a_reader_error_with_the_file_name(
    tmp_path: pathlib.Path,
) -> None:
    """A YAML reader failure must name the card rather than escape."""
    path = _write_bytes(tmp_path, b"schema_version: 1\n\x00")

    with pytest.raises(PricingCatalogueError, match=rf"{path.name}: invalid YAML"):
        FilePricingCatalogue(tmp_path)


def test_loader_reports_an_impossible_yaml_timestamp(
    tmp_path: pathlib.Path,
) -> None:
    """An unquoted impossible date must name the card rather than escape."""
    body = _card().replace(
        'retrieved_at: "2026-06-01T00:00:00Z"',
        "retrieved_at: 2026-02-30T00:00:00Z",
    )
    _write_card(tmp_path, body)

    with pytest.raises(PricingCatalogueError, match=r"openai\.yaml: invalid YAML"):
        FilePricingCatalogue(tmp_path)
