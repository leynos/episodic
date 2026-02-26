"""Helpers for TEI header provenance metadata.

This module builds and merges provenance metadata for TEI headers so
provenance capture is consistent across ingestion and future script generation
flows.
"""

import datetime as dt
import typing as typ

if typ.TYPE_CHECKING:
    from .domain import JsonMapping, SourceDocumentInput

type CaptureContext = typ.Literal["source_ingestion", "script_generation"]


class SourcePriorityRecord(typ.TypedDict):
    """Typed source-priority entry stored in TEI provenance payloads."""

    priority: int
    source_uri: str
    source_type: str
    weight: float
    content_hash: str


class TeiHeaderProvenanceRecord(typ.TypedDict):
    """Typed TEI header provenance payload."""

    capture_context: CaptureContext
    ingestion_timestamp: str
    source_priorities: list[SourcePriorityRecord]
    reviewer_identities: list[str]


def _normalize_capture_timestamp(captured_at: dt.datetime) -> str:
    """Return an ISO-8601 timestamp normalized to UTC."""
    if captured_at.tzinfo is None:
        msg = "captured_at must be timezone-aware."
        raise ValueError(msg)
    return captured_at.astimezone(dt.UTC).isoformat()


def _normalize_reviewer_identities(
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
) -> list[SourcePriorityRecord]:
    """Build deterministic priority records from source inputs."""
    ordered_sources = sorted(
        sources,
        key=lambda source: -source.weight,
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
) -> TeiHeaderProvenanceRecord:
    """Build provenance metadata to embed in a TEI header payload.

    Parameters
    ----------
    sources : list[SourceDocumentInput]
        Source documents participating in canonical ingestion.
    captured_at : dt.datetime
        Timestamp when provenance is captured. Must be timezone-aware.
    reviewer_identities : list[str]
        Reviewer identifiers to store in first-seen order after
        normalization.
    capture_context : CaptureContext
        Workflow context that generated this provenance payload.

    Returns
    -------
    TeiHeaderProvenanceRecord
        Structured provenance metadata suitable for TEI header persistence.
    """
    return {
        "capture_context": capture_context,
        "ingestion_timestamp": _normalize_capture_timestamp(captured_at),
        "source_priorities": _build_source_priorities(sources),
        "reviewer_identities": _normalize_reviewer_identities(reviewer_identities),
    }


def merge_tei_header_provenance(
    payload: JsonMapping,
    provenance: TeiHeaderProvenanceRecord,
) -> JsonMapping:
    """Return a TEI header payload extended with provenance metadata.

    Parameters
    ----------
    payload : JsonMapping
        Existing parsed TEI header payload.
    provenance : TeiHeaderProvenanceRecord
        Provenance payload to attach under ``episodic_provenance``.

    Returns
    -------
    JsonMapping
        Copy of ``payload`` with merged ``episodic_provenance`` metadata.
    """
    existing_provenance = payload.get("episodic_provenance")
    if isinstance(existing_provenance, dict):
        merged_provenance: JsonMapping = {
            **typ.cast("JsonMapping", existing_provenance),
            **provenance,
        }
    else:
        merged_provenance = dict(provenance)
    return {**payload, "episodic_provenance": merged_provenance}
