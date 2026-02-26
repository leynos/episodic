"""Unit tests for source normalization adapters."""

from __future__ import annotations

import pytest
from _ingestion_service_helpers import _make_raw_source

from episodic.canonical.adapters.normalizer import InMemorySourceNormalizer
from episodic.canonical.tei import parse_tei_header


@pytest.fixture
def normalizer() -> InMemorySourceNormalizer:
    """Provide a normalizer instance for adapter tests."""
    return InMemorySourceNormalizer()


@pytest.mark.asyncio
async def test_normalizer_produces_valid_tei_fragment(
    normalizer: InMemorySourceNormalizer,
) -> None:
    """The normalizer produces a NormalizedSource with parseable TEI XML."""
    raw = _make_raw_source(
        source_type="transcript",
        content="Transcript content here",
        metadata={"title": "My Transcript"},
    )

    result = await normalizer.normalize(raw)

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
async def test_normalizer_unknown_source_type_uses_defaults(
    normalizer: InMemorySourceNormalizer,
) -> None:
    """An unknown source type gets mid-range fallback scores."""
    raw = _make_raw_source(source_type="unknown_format")

    result = await normalizer.normalize(raw)

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
async def test_normalizer_infers_title_from_content(
    normalizer: InMemorySourceNormalizer,
) -> None:
    """Without a metadata title, the first content line is used."""
    raw = _make_raw_source(
        content="First line of content\nSecond line",
        metadata={},
    )

    result = await normalizer.normalize(raw)

    assert result.title == "First line of content", (
        "Expected title to be inferred from the first content line."
    )


@pytest.mark.asyncio
async def test_normalizer_infers_title_from_source_type(
    normalizer: InMemorySourceNormalizer,
) -> None:
    """With no metadata title and empty content, source_type is used."""
    raw = _make_raw_source(
        source_type="press_release",
        content="",
        metadata={},
    )

    result = await normalizer.normalize(raw)

    assert result.title == "Press Release", (
        "Expected title fallback to convert source type into title case."
    )
