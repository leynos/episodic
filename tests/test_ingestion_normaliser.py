"""Unit tests for source normalisation adapters."""

from __future__ import annotations

import pytest
from _ingestion_service_helpers import _make_raw_source

from episodic.canonical.adapters.normaliser import InMemorySourceNormaliser
from episodic.canonical.tei import parse_tei_header


@pytest.mark.asyncio
async def test_normaliser_produces_valid_tei_fragment() -> None:
    """The normaliser produces a NormalisedSource with parseable TEI XML."""
    normaliser = InMemorySourceNormaliser()
    raw = _make_raw_source(
        source_type="transcript",
        content="Transcript content here",
        metadata={"title": "My Transcript"},
    )

    result = await normaliser.normalise(raw)

    parsed = parse_tei_header(result.tei_fragment)
    assert parsed.title == "My Transcript", (
        "Expected parsed TEI title to match metadata title."
    )
    assert result.quality_score == pytest.approx(0.9), (
        "Expected transcript quality score to use transcript defaults."
    )
    assert result.freshness_score == pytest.approx(0.8), (
        "Expected transcript freshness score to use transcript defaults."
    )
    assert result.reliability_score == pytest.approx(0.9), (
        "Expected transcript reliability score to use transcript defaults."
    )
    assert result.source_input.source_type == "transcript", (
        "Expected source type to be preserved from raw input."
    )
    assert result.source_input.source_uri == raw.source_uri, (
        "Expected source URI to be preserved from raw input."
    )


@pytest.mark.asyncio
async def test_normaliser_unknown_source_type_uses_defaults() -> None:
    """An unknown source type gets mid-range fallback scores."""
    normaliser = InMemorySourceNormaliser()
    raw = _make_raw_source(source_type="unknown_format")

    result = await normaliser.normalise(raw)

    assert result.quality_score == pytest.approx(0.5), (
        "Expected unknown source types to fall back to default quality."
    )
    assert result.freshness_score == pytest.approx(0.5), (
        "Expected unknown source types to fall back to default freshness."
    )
    assert result.reliability_score == pytest.approx(0.5), (
        "Expected unknown source types to fall back to default reliability."
    )


@pytest.mark.asyncio
async def test_normaliser_infers_title_from_content() -> None:
    """Without a metadata title, the first content line is used."""
    normaliser = InMemorySourceNormaliser()
    raw = _make_raw_source(
        content="First line of content\nSecond line",
        metadata={},
    )

    result = await normaliser.normalise(raw)

    assert result.title == "First line of content", (
        "Expected title to be inferred from the first content line."
    )


@pytest.mark.asyncio
async def test_normaliser_infers_title_from_source_type() -> None:
    """With no metadata title and empty content, source_type is used."""
    normaliser = InMemorySourceNormaliser()
    raw = _make_raw_source(
        source_type="press_release",
        content="",
        metadata={},
    )

    result = await normaliser.normalise(raw)

    assert result.title == "Press Release", (
        "Expected title fallback to convert source type into title case."
    )
