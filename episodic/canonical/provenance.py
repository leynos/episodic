"""Helpers for TEI header provenance metadata.

This module builds and merges provenance metadata for TEI headers so
provenance capture is consistent across ingestion and future script generation
flows.
"""

from __future__ import annotations

import datetime as dt
import typing as typ

if typ.TYPE_CHECKING:
    from .domain import JsonMapping, SourceDocumentInput

type CaptureContext = typ.Literal["source_ingestion", "script_generation"]


def _normalise_capture_timestamp(captured_at: dt.datetime) -> str:
    """Return an ISO-8601 timestamp normalized to UTC."""
    if captured_at.tzinfo is None:
        msg = "captured_at must be timezone-aware."
        raise ValueError(msg)
    return captured_at.astimezone(dt.UTC).isoformat()


def _normalise_reviewer_identities(
    reviewer_identities: list[str],
) -> list[str]:
    """Return reviewer identities stripped, deduplicated, and ordered."""
    # Preserve first-seen order while dropping blanks and duplicates.
    return list(
        dict.fromkeys(
            identity.strip() for identity in reviewer_identities if identity.strip()
        ),
    )


def _build_source_priorities(
    sources: list[SourceDocumentInput],
) -> list[JsonMapping]:
    """Build deterministic priority records from source inputs."""
    ordered_sources = sorted(
        sources,
        key=lambda source: (-source.weight, source.source_uri, source.source_type),
    )
    return [
        {
            "priority": priority,
            "source_uri": source.source_uri,
            "source_type": source.source_type,
            "weight": source.weight,
            "content_hash": source.content_hash,
        }
        for priority, source in enumerate(ordered_sources, start=1)
    ]


def build_tei_header_provenance(
    sources: list[SourceDocumentInput],
    captured_at: dt.datetime,
    reviewer_identities: list[str],
    capture_context: CaptureContext,
) -> JsonMapping:
    """Build provenance metadata to embed in a TEI header payload."""
    return {
        "capture_context": capture_context,
        "ingestion_timestamp": _normalise_capture_timestamp(captured_at),
        "source_priorities": _build_source_priorities(sources),
        "reviewer_identities": _normalise_reviewer_identities(reviewer_identities),
    }


def merge_tei_header_provenance(
    payload: JsonMapping,
    provenance: JsonMapping,
) -> JsonMapping:
    """Return a TEI header payload extended with provenance metadata."""
    return {**payload, "episodic_provenance": provenance}
