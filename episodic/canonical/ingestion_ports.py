"""Port protocols for multi-source ingestion.

This module defines protocol interfaces for the three extension points in the
multi-source ingestion pipeline: normalisation, weighting, and conflict
resolution. Adapters implement these protocols so different strategies can be
swapped without impacting the orchestration logic.

Examples
--------
Implement a custom normaliser that satisfies the protocol:

>>> class MyNormaliser:
...     async def normalise(self, raw_source: RawSourceInput) -> NormalisedSource:
...         ...
"""

from __future__ import annotations

import typing as typ

if typ.TYPE_CHECKING:
    from .domain import JsonMapping
    from .ingestion import (
        ConflictOutcome,
        NormalisedSource,
        RawSourceInput,
        WeightingResult,
    )


class SourceNormaliser(typ.Protocol):
    """Normalises a raw source into a TEI fragment with quality scores.

    Implementations convert heterogeneous source content (transcripts, briefs,
    Really Simple Syndication (RSS) feeds, press releases, and research notes)
    into normalised TEI fragments with classifier-assigned quality, freshness,
    and reliability scores.

    Methods
    -------
    normalise(raw_source)
        Normalise a single raw source into a TEI-compatible fragment.
    """

    async def normalise(
        self,
        raw_source: RawSourceInput,
    ) -> NormalisedSource:
        """Normalise a raw source into a TEI fragment.

        Parameters
        ----------
        raw_source : RawSourceInput
            The raw source to normalise.

        Returns
        -------
        NormalisedSource
            The normalised source with TEI fragment and quality scores.
        """
        ...


class WeightingStrategy(typ.Protocol):
    """Computes weights for normalised sources using series configuration.

    Implementations apply weighting heuristics to normalised sources,
    producing a computed weight for each source based on quality, freshness,
    and reliability scores combined with series-level configuration
    coefficients.

    Methods
    -------
    compute_weights(sources, series_configuration)
        Compute weights for a list of normalised sources.
    """

    async def compute_weights(
        self,
        sources: list[NormalisedSource],
        series_configuration: JsonMapping,
    ) -> list[WeightingResult]:
        """Compute weights for normalised sources.

        Parameters
        ----------
        sources : list[NormalisedSource]
            Normalised sources to weight.
        series_configuration : JsonMapping
            Series-level configuration containing weighting coefficients.

        Returns
        -------
        list[WeightingResult]
            Weighted sources with computed weights and factor breakdowns.
        """
        ...


class ConflictResolver(typ.Protocol):
    """Resolves conflicts between weighted sources into canonical TEI.

    Implementations select which sources contribute to the canonical episode
    and which are rejected, producing merged TEI XML and audit metadata.
    Rejected sources are retained for provenance.

    Methods
    -------
    resolve(weighted_sources)
        Resolve conflicts between weighted sources.
    """

    async def resolve(
        self,
        weighted_sources: list[WeightingResult],
    ) -> ConflictOutcome:
        """Resolve conflicts between weighted sources.

        Parameters
        ----------
        weighted_sources : list[WeightingResult]
            Sources with computed weights to resolve.

        Returns
        -------
        ConflictOutcome
            The merged canonical TEI and conflict resolution metadata.
        """
        ...
