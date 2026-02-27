"""Domain value objects for multi-source ingestion.

This module defines the intermediate representations used during the
multi-source ingestion pipeline: raw inputs, normalized fragments, weighting
results, and conflict resolution outcomes.

Examples
--------
Build a raw source input for ingestion:

>>> raw = RawSourceInput(
...     source_type="transcript",
...     source_uri="s3://bucket/transcript.txt",
...     content="Episode content...",
...     content_hash="abc123",
...     metadata={"language": "en"},
... )
"""

import dataclasses as dc
import typing as typ

if typ.TYPE_CHECKING:
    from .domain import JsonMapping, SourceDocumentInput


@dc.dataclass(frozen=True, slots=True)
class RawSourceInput:
    """A single raw source before normalization.

    Attributes
    ----------
    source_type : str
        Type classifier such as ``"transcript"``, ``"brief"``, ``"rss"``,
        ``"press_release"``, or ``"research_notes"``.
    source_uri : str
        URI or path identifying the source location.
    content : str
        Raw textual content of the source.
    content_hash : str
        Hash of the raw content for deduplication.
    metadata : JsonMapping
        Arbitrary metadata from the source.
    """

    source_type: str
    source_uri: str
    content: str
    content_hash: str
    metadata: JsonMapping


@dc.dataclass(frozen=True, slots=True)
class NormalizedSource:
    """A source document after normalization into a TEI-compatible fragment.

    Attributes
    ----------
    source_input : SourceDocumentInput
        Persistence-ready metadata derived from the original raw source.
    title : str
        Title extracted or inferred from the source content.
    tei_fragment : str
        Normalized TEI XML fragment for this source.
    quality_score : float
        Classifier-assigned quality score in the range [0, 1].
    freshness_score : float
        Temporal freshness score in the range [0, 1].
    reliability_score : float
        Source reliability score in the range [0, 1].
    """

    source_input: SourceDocumentInput
    title: str
    tei_fragment: str
    quality_score: float
    freshness_score: float
    reliability_score: float


@dc.dataclass(frozen=True, slots=True)
class WeightingResult:
    """Computed weight for a single normalized source.

    Attributes
    ----------
    source : NormalizedSource
        The normalized source that was weighted.
    computed_weight : float
        Final weight in the range [0, 1] after heuristic application.
    factors : JsonMapping
        Breakdown of weighting factors for audit and provenance.
    """

    source: NormalizedSource
    computed_weight: float
    factors: JsonMapping


@dc.dataclass(frozen=True, slots=True)
class ConflictOutcome:
    """Result of conflict resolution across all weighted sources.

    Attributes
    ----------
    merged_tei_xml : str
        The final merged TEI XML representing the canonical content.
    merged_title : str
        The resolved title for the canonical episode.
    preferred_sources : list[WeightingResult]
        Sources that contributed to the canonical output.
    rejected_sources : list[WeightingResult]
        Sources that were overridden during conflict resolution, with
        weights and factors preserved for audit.
    resolution_notes : str
        Human-readable summary of the conflict resolution decision.
    """

    merged_tei_xml: str
    merged_title: str
    preferred_sources: list[WeightingResult]
    rejected_sources: list[WeightingResult]
    resolution_notes: str


@dc.dataclass(frozen=True, slots=True)
class MultiSourceRequest:
    """Input payload for multi-source ingestion.

    Attributes
    ----------
    raw_sources : list[RawSourceInput]
        Heterogeneous source inputs to normalize, weight, and merge.
    series_slug : str
        Slug identifying the target series profile.
    requested_by : str | None
        Actor requesting the ingestion, used for audit trails.
    """

    raw_sources: list[RawSourceInput]
    series_slug: str
    requested_by: str | None
