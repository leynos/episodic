"""Unit tests for TEI header provenance helpers."""

from __future__ import annotations

import datetime as dt
import typing as typ

import pytest

from episodic.canonical.domain import SourceDocumentInput
from episodic.canonical.provenance import (
    build_tei_header_provenance,
    merge_tei_header_provenance,
)


def _source(
    source_uri: str,
    *,
    weight: float,
) -> SourceDocumentInput:
    """Build a source document input for provenance tests."""
    return SourceDocumentInput(
        source_type="web",
        source_uri=source_uri,
        weight=weight,
        content_hash=f"hash-{source_uri}",
        metadata={},
    )


def test_build_tei_header_provenance_orders_sources_by_priority() -> None:
    """Source priorities are ordered by descending weight."""
    provenance = build_tei_header_provenance(
        sources=[
            _source("https://example.com/second", weight=0.5),
            _source("https://example.com/first", weight=0.9),
        ],
        captured_at=dt.datetime(2026, 2, 18, 12, 0, tzinfo=dt.UTC),
        reviewer_identities=["reviewer@example.com"],
        capture_context="source_ingestion",
    )

    priorities = provenance["source_priorities"]
    assert isinstance(priorities, list), "Expected source priorities as a list."
    assert priorities[0]["source_uri"] == "https://example.com/first", (
        "Expected highest-weighted source to be first."
    )
    assert priorities[1]["source_uri"] == "https://example.com/second", (
        "Expected lower-weighted source to be second."
    )
    assert priorities[0]["priority"] == 1, (
        "Expected highest-weighted source to have priority rank one."
    )
    assert priorities[1]["priority"] == 2, (
        "Expected lower-weighted source to have priority rank two."
    )


def test_build_tei_header_provenance_is_deterministic_for_ties() -> None:
    """Tie weights preserve source input order for deterministic ranking."""
    provenance = build_tei_header_provenance(
        sources=[
            _source("https://example.com/zeta", weight=0.7),
            _source("https://example.com/alpha", weight=0.7),
        ],
        captured_at=dt.datetime(2026, 2, 18, 12, 0, tzinfo=dt.UTC),
        reviewer_identities=["reviewer@example.com"],
        capture_context="source_ingestion",
    )

    priorities = provenance["source_priorities"]
    assert isinstance(priorities, list), "Expected source priorities as a list."
    assert priorities[0]["source_uri"] == "https://example.com/zeta", (
        "Expected equal weights to preserve request ordering."
    )
    assert priorities[1]["source_uri"] == "https://example.com/alpha", (
        "Expected equal weights to preserve request ordering."
    )


def test_build_tei_header_provenance_rejects_naive_timestamp() -> None:
    """Naive capture timestamps are rejected."""
    with pytest.raises(ValueError, match=r"captured_at must be timezone-aware\."):
        build_tei_header_provenance(
            sources=[_source("https://example.com/source", weight=0.5)],
            captured_at=dt.datetime(2026, 2, 18, 12, 0, tzinfo=dt.UTC).replace(
                tzinfo=None,
            ),
            reviewer_identities=["reviewer@example.com"],
            capture_context="source_ingestion",
        )


def test_build_tei_header_provenance_normalises_reviewer_identities() -> None:
    """Reviewer identities are stripped, deduplicated, and blank-filtered."""
    provenance = build_tei_header_provenance(
        sources=[_source("https://example.com/source", weight=0.5)],
        captured_at=dt.datetime(2026, 2, 18, 12, 0, tzinfo=dt.UTC),
        reviewer_identities=[
            "  alice@example.com  ",
            "",
            "alice@example.com",
            "bob@example.com",
        ],
        capture_context="source_ingestion",
    )

    assert provenance["reviewer_identities"] == [
        "alice@example.com",
        "bob@example.com",
    ], "Expected normalized reviewer identities in first-seen order."


def test_build_tei_header_provenance_with_empty_sources() -> None:
    """Empty source lists produce empty source-priority records."""
    provenance = build_tei_header_provenance(
        sources=[],
        captured_at=dt.datetime(2026, 2, 18, 12, 0, tzinfo=dt.UTC),
        reviewer_identities=["reviewer@example.com"],
        capture_context="source_ingestion",
    )

    assert provenance["source_priorities"] == [], (
        "Expected empty priorities when no sources are provided."
    )


def test_build_tei_header_provenance_supports_script_generation_context() -> None:
    """Provenance includes script-generation capture context."""
    provenance = build_tei_header_provenance(
        sources=[],
        captured_at=dt.datetime(2026, 2, 18, 12, 0, tzinfo=dt.UTC),
        reviewer_identities=["editor@example.com"],
        capture_context="script_generation",
    )

    assert provenance["capture_context"] == "script_generation", (
        "Expected script-generation capture context to be preserved."
    )
    assert provenance["reviewer_identities"] == ["editor@example.com"], (
        "Expected reviewer identities to round-trip in provenance."
    )


def test_merge_tei_header_provenance_adds_payload_without_mutating_input() -> None:
    """Merging provenance returns a new payload with extension metadata."""
    payload = {"fileDesc": {"title": "Bridgewater"}}
    provenance = build_tei_header_provenance(
        sources=[],
        captured_at=dt.datetime(2026, 2, 18, 12, 0, tzinfo=dt.UTC),
        reviewer_identities=[],
        capture_context="source_ingestion",
    )

    merged = merge_tei_header_provenance(payload, provenance)

    assert merged["episodic_provenance"] == provenance, (
        "Expected merged payload to include provenance extension."
    )
    assert "episodic_provenance" not in payload, (
        "Expected merge to avoid mutating the original payload."
    )


def test_merge_tei_header_provenance_preserves_unrelated_existing_keys() -> None:
    """Merging provenance preserves unknown keys from existing payload metadata."""
    payload = {
        "fileDesc": {"title": "Bridgewater"},
        "episodic_provenance": {"legacy_key": "legacy-value"},
    }
    provenance = build_tei_header_provenance(
        sources=[_source("https://example.com/source", weight=1.0)],
        captured_at=dt.datetime(2026, 2, 18, 12, 0, tzinfo=dt.UTC),
        reviewer_identities=["reviewer@example.com"],
        capture_context="source_ingestion",
    )

    merged = merge_tei_header_provenance(payload, provenance)

    merged_provenance = merged["episodic_provenance"]
    assert isinstance(merged_provenance, dict), (
        "Expected merged provenance payload to remain a mapping."
    )
    merged_dict = typ.cast("dict[str, object]", merged_provenance)
    assert merged_dict["legacy_key"] == "legacy-value", (
        "Expected merge to preserve unknown existing provenance keys."
    )
