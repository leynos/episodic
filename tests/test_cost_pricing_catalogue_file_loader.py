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

    snapshot = await FilePricingCatalogue.from_directory(tmp_path).resolve(_SUBJECT)

    assert snapshot.effective_from == dt.datetime(2026, 6, 1, tzinfo=dt.UTC), (
        f"expected the parsed effective date, got {snapshot.effective_from!r}"
    )
    assert snapshot.effective_from is not None, (
        "the loaded card declares an effective date"
    )
    assert snapshot.effective_from.tzinfo is not None, (
        "the loaded effective date must be timezone-aware"
    )


@pytest.mark.parametrize("invalid_value", ["false", "0", "[]", "{}"])
def test_loader_rejects_a_non_string_effective_from(
    tmp_path: pathlib.Path,
    invalid_value: str,
) -> None:
    """Present but non-string effective dates must fail loading."""
    _write_card(tmp_path, _card(effective_from=invalid_value))

    with pytest.raises(PricingCatalogueError, match="effective_from"):
        FilePricingCatalogue.from_directory(tmp_path)


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
            _card().replace("unit: token", "unit: kilogram"),
            "kilogram",
            id="unknown-rate-unit",
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
        FilePricingCatalogue.from_directory(tmp_path)


def test_loader_reports_undecodable_bytes_with_the_file_name(
    tmp_path: pathlib.Path,
) -> None:
    """Invalid UTF-8 surfaces as a catalogue error that names the card."""
    path = _write_bytes(tmp_path, b"\xff\xfe")

    with pytest.raises(PricingCatalogueError, match=rf"{path.name}: cannot read card"):
        FilePricingCatalogue.from_directory(tmp_path)


def test_loader_reports_unreadable_cards_with_the_file_name(
    tmp_path: pathlib.Path,
) -> None:
    """A card path that cannot be read surfaces as a catalogue error."""
    (tmp_path / "broken.yaml").mkdir()

    with pytest.raises(PricingCatalogueError, match=r"cannot read card.*broken\.yaml"):
        FilePricingCatalogue.from_directory(tmp_path)
