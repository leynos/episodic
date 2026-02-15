"""Multi-source ingestion orchestrator.

This module provides the high-level ``ingest_multi_source`` function that
normalises heterogeneous source documents, computes weights, resolves
conflicts, and delegates persistence to the existing ``ingest_sources``
service.

Examples
--------
Ingest multiple sources within a unit-of-work session:

>>> pipeline = IngestionPipeline(normaliser, weighting, resolver)
>>> async with SqlAlchemyUnitOfWork(session_factory) as uow:
...     episode = await ingest_multi_source(
...         uow, profile, request, pipeline,
...     )
"""

from __future__ import annotations

import dataclasses as dc
import typing as typ

from episodic.logging import get_logger, log_info

from .domain import IngestionRequest, SourceDocumentInput
from .services import ingest_sources

logger = get_logger(__name__)

if typ.TYPE_CHECKING:
    from .domain import CanonicalEpisode, SeriesProfile
    from .ingestion import (
        ConflictOutcome,
        MultiSourceRequest,
        NormalisedSource,
        RawSourceInput,
        WeightingResult,
    )
    from .ingestion_ports import (
        ConflictResolver,
        SourceNormaliser,
        WeightingStrategy,
    )
    from .ports import CanonicalUnitOfWork


@dc.dataclass(frozen=True, slots=True)
class IngestionPipeline:
    """Bundles the three port adapters for multi-source ingestion.

    Attributes
    ----------
    normaliser : SourceNormaliser
        Adapter for normalising raw sources into TEI fragments.
    weighting : WeightingStrategy
        Adapter for computing source weights.
    resolver : ConflictResolver
        Adapter for resolving conflicts between weighted sources.
    """

    normaliser: SourceNormaliser
    weighting: WeightingStrategy
    resolver: ConflictResolver


def _build_source_document_inputs(
    raw_sources: list[RawSourceInput],
    weighted_sources: list[WeightingResult],
) -> list[SourceDocumentInput]:
    """Build persistence-ready source inputs from weighted results.

    Each raw source is matched to its weighted result so the computed
    weight replaces the placeholder weight assigned during normalisation.
    """
    weight_by_uri: dict[str, float] = {
        wr.source.source_input.source_uri: wr.computed_weight for wr in weighted_sources
    }
    return [
        SourceDocumentInput(
            source_type=raw.source_type,
            source_uri=raw.source_uri,
            weight=weight_by_uri.get(raw.source_uri, 0.0),
            content_hash=raw.content_hash,
            metadata=raw.metadata,
        )
        for raw in raw_sources
    ]


async def _normalise_sources(
    raw_sources: list[RawSourceInput],
    normaliser: SourceNormaliser,
) -> list[NormalisedSource]:
    """Normalise all raw sources into TEI fragments."""
    return [await normaliser.normalise(raw) for raw in raw_sources]


async def _compute_weights(
    normalised: list[NormalisedSource],
    series_configuration: dict[str, object],
    weighting: WeightingStrategy,
) -> list[WeightingResult]:
    """Compute weights for all normalised sources."""
    return await weighting.compute_weights(
        normalised,
        series_configuration,
    )


async def _resolve_conflicts(
    weighted: list[WeightingResult],
    resolver: ConflictResolver,
) -> ConflictOutcome:
    """Resolve conflicts between weighted sources."""
    return await resolver.resolve(weighted)


async def ingest_multi_source(
    uow: CanonicalUnitOfWork,
    series_profile: SeriesProfile,
    request: MultiSourceRequest,
    pipeline: IngestionPipeline,
) -> CanonicalEpisode:
    """Normalise, weight, resolve, and persist multi-source content.

    This orchestrator runs the full ingestion pipeline:

    1. Normalise each raw source into a TEI fragment via the normaliser.
    2. Compute weights using the weighting strategy and series
       configuration.
    3. Resolve conflicts between sources via the conflict resolver.
    4. Build an ``IngestionRequest`` with the merged TEI and computed
       weights.
    5. Delegate persistence to ``ingest_sources``.

    Parameters
    ----------
    uow : CanonicalUnitOfWork
        Unit-of-work boundary providing repository access and transaction
        scope.
    series_profile : SeriesProfile
        Series profile that owns the canonical episode.
    request : MultiSourceRequest
        Multi-source ingestion payload with raw source inputs.
    pipeline : IngestionPipeline
        Bundled normaliser, weighting strategy, and conflict resolver.

    Returns
    -------
    CanonicalEpisode
        Persisted canonical episode representing the merged content.

    Raises
    ------
    ValueError
        If ``request.raw_sources`` is empty.
    TypeError
        If the merged TEI header is missing from the parsed payload.
    ValueError
        If the merged TEI header title is missing or blank.
    """
    if not request.raw_sources:
        msg = "At least one raw source is required for multi-source ingestion."
        raise ValueError(msg)

    normalised = await _normalise_sources(
        request.raw_sources,
        pipeline.normaliser,
    )
    weighted = await _compute_weights(
        normalised,
        series_profile.configuration,
        pipeline.weighting,
    )
    outcome = await _resolve_conflicts(weighted, pipeline.resolver)

    source_inputs = _build_source_document_inputs(
        request.raw_sources,
        weighted,
    )

    ingestion_request = IngestionRequest(
        tei_xml=outcome.merged_tei_xml,
        sources=source_inputs,
        requested_by=request.requested_by,
    )

    episode = await ingest_sources(
        uow,
        series_profile,
        ingestion_request,
    )

    log_info(
        logger,
        "Multi-source ingestion complete: %s sources, "
        "%s preferred, %s rejected. Episode %s.",
        len(request.raw_sources),
        len(outcome.preferred_sources),
        len(outcome.rejected_sources),
        episode.id,
    )

    return episode
