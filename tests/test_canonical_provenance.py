"""Unit tests for TEI header provenance helpers."""

from __future__ import annotations

import datetime as dt

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


def test_build_tei_header_provenance_is_deterministic_for_ties() -> None:
    """Tie weights are ordered deterministically by source URI."""
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
    assert priorities[0]["source_uri"] == "https://example.com/alpha", (
        "Expected lexical URI tie-break ordering."
    )
    assert priorities[1]["source_uri"] == "https://example.com/zeta", (
        "Expected lexical URI tie-break ordering."
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
    provenance = {
        "capture_context": "source_ingestion",
        "source_priorities": [],
        "ingestion_timestamp": "2026-02-18T12:00:00+00:00",
        "reviewer_identities": [],
    }

    merged = merge_tei_header_provenance(payload, provenance)

    assert merged["episodic_provenance"] == provenance, (
        "Expected merged payload to include provenance extension."
    )
    assert "episodic_provenance" not in payload, (
        "Expected merge to avoid mutating the original payload."
    )
