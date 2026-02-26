"""Multi-source ingestion orchestrator.

This module provides the high-level ``ingest_multi_source`` function that
normalizes heterogeneous source documents, computes weights, resolves
conflicts, and delegates persistence to the existing ``ingest_sources``
service.

Examples
--------
Ingest multiple sources within a unit-of-work session:

>>> pipeline = IngestionPipeline(normalizer, weighting, resolver)
>>> async with SqlAlchemyUnitOfWork(session_factory) as uow:
...     episode = await ingest_multi_source(
...         uow, profile, request, pipeline,
...     )
"""

from __future__ import annotations

import asyncio
import dataclasses as dc
import typing as typ

from episodic.asyncio_tasks import TaskMetadata, create_task
from episodic.logging import get_logger, log_info

from .domain import IngestionRequest
from .services import ingest_sources

logger = get_logger(__name__)

if typ.TYPE_CHECKING:
    from .domain import CanonicalEpisode, SeriesProfile, SourceDocumentInput
    from .ingestion import (
        ConflictOutcome,
        MultiSourceRequest,
        NormalisedSource,
        WeightingResult,
    )
    from .ingestion_ports import (
        ConflictResolver,
        SourceNormalizer,
        WeightingStrategy,
    )
    from .ports import CanonicalUnitOfWork


@dc.dataclass(frozen=True, slots=True)
class IngestionPipeline:
    """Bundles the three port adapters for multi-source ingestion.

    Attributes
    ----------
    normalizer : SourceNormalizer
        Adapter for normalizing raw sources into TEI fragments.
    weighting : WeightingStrategy
        Adapter for computing source weights.
    resolver : ConflictResolver
        Adapter for resolving conflicts between weighted sources.
    """

    normalizer: SourceNormalizer
    weighting: WeightingStrategy
    resolver: ConflictResolver


def _build_conflict_metadata(
    outcome: ConflictOutcome,
) -> dict[str, object]:
    """Build a serialisable conflict-resolution audit summary."""
    return {
        "preferred_sources": [
            wr.source.source_input.source_uri for wr in outcome.preferred_sources
        ],
        "rejected_sources": [
            wr.source.source_input.source_uri for wr in outcome.rejected_sources
        ],
        "resolution_notes": outcome.resolution_notes,
    }


def _enrich_source_metadata(
    weighted_sources: list[WeightingResult],
    conflict_metadata: dict[str, object],
) -> list[SourceDocumentInput]:
    """Replace placeholder weights and inject conflict-resolution metadata.

    Each source's ``metadata`` dictionary is augmented with a
    ``"conflict_resolution"`` key containing the audit summary produced
    by the conflict resolver.
    """
    return [
        dc.replace(
            wr.source.source_input,
            weight=wr.computed_weight,
            metadata={
                **wr.source.source_input.metadata,
                "conflict_resolution": conflict_metadata,
            },
        )
        for wr in weighted_sources
    ]


def _validate_ingestion_request(
    request: MultiSourceRequest,
    series_profile: SeriesProfile,
) -> None:
    """Validate a multi-source ingestion request against series context.

    Parameters
    ----------
    request : MultiSourceRequest
        Multi-source ingestion payload to validate.
    series_profile : SeriesProfile
        Series profile expected to match the request's series slug.

    Raises
    ------
    ValueError
        Raised when ``request.raw_sources`` is empty or when
        ``request.series_slug`` does not match ``series_profile.slug``.
    """
    if not request.raw_sources:
        msg = "At least one raw source is required for multi-source ingestion."
        raise ValueError(msg)

    if request.series_slug != series_profile.slug:
        msg = (
            f"Series slug mismatch: request has {request.series_slug!r} "
            f"but profile has {series_profile.slug!r}."
        )
        raise ValueError(msg)


def _normalisation_task_metadata(
    *,
    series_slug: str,
    source_index: int,
) -> TaskMetadata:
    """Build task metadata for a source-normalization task."""
    return {
        "operation_name": "canonical.ingestion.normalise",
        "correlation_id": series_slug,
        "priority_hint": source_index,
    }


def _create_normalisation_tasks(
    *,
    pipeline: IngestionPipeline,
    request: MultiSourceRequest,
) -> list[asyncio.Task[NormalisedSource]]:
    """Create normalization tasks with metadata-aware task kwargs."""
    return [
        create_task(
            pipeline.normalizer.normalize(raw_source),
            name=f"canonical.ingestion.normalise:{source_index}",
            eager_start=True,
            metadata=_normalisation_task_metadata(
                series_slug=request.series_slug,
                source_index=source_index,
            ),
        )
        for source_index, raw_source in enumerate(request.raw_sources, start=1)
    ]


async def ingest_multi_source(
    uow: CanonicalUnitOfWork,
    series_profile: SeriesProfile,
    request: MultiSourceRequest,
    pipeline: IngestionPipeline,
) -> CanonicalEpisode:
    """Normalize, weight, resolve, and persist multi-source content.

    This orchestrator runs the full ingestion pipeline:

    1. Normalize each raw source into a TEI fragment via the normalizer
       (concurrently using ``asyncio.gather``).
    2. Compute weights using the weighting strategy and series
       configuration.
    3. Resolve conflicts between sources via the conflict resolver.
    4. Build an ``IngestionRequest`` with the merged TEI, computed
       weights, and conflict-resolution metadata.
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
        Bundled normalizer, weighting strategy, and conflict resolver.

    Returns
    -------
    CanonicalEpisode
        Persisted canonical episode representing the merged content.

    Raises
    ------
    ValueError
        If ``request.raw_sources`` is empty or if
        ``request.series_slug`` does not match
        ``series_profile.slug``.
    """
    _validate_ingestion_request(request, series_profile)

    normalisation_tasks = _create_normalisation_tasks(
        pipeline=pipeline,
        request=request,
    )
    normalized = list(await asyncio.gather(*normalisation_tasks))

    weighted = await pipeline.weighting.compute_weights(
        normalized,
        series_profile.configuration,
    )
    outcome = await pipeline.resolver.resolve(weighted)

    conflict_metadata = _build_conflict_metadata(outcome)
    source_inputs = _enrich_source_metadata(weighted, conflict_metadata)
    ingestion_request = IngestionRequest(
        tei_xml=outcome.merged_tei_xml,
        sources=source_inputs,
        requested_by=request.requested_by,
    )

    episode = await ingest_sources(
        uow=uow, series_profile=series_profile, request=ingestion_request
    )

    log_info(
        logger,
        "Multi-source ingestion complete: %s sources, "
        "%s preferred, %s rejected. Episode %s.",
        len(source_inputs),
        len(outcome.preferred_sources),
        len(outcome.rejected_sources),
        episode.id,
    )

    return episode
