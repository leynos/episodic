"""Reference conflict resolver adapter.

This adapter resolves conflicts by selecting the highest-weighted source as
the canonical content. All other sources are recorded as rejected with their
weights preserved for audit.

Examples
--------
Resolve conflicts between weighted sources:

>>> resolver = HighestWeightConflictResolver()
>>> outcome = await resolver.resolve(weighted_sources)
>>> outcome.merged_title
'Preferred Source Title'
"""

from __future__ import annotations

from episodic.canonical.ingestion import ConflictOutcome, WeightingResult


def _build_resolution_notes(
    preferred: list[WeightingResult],
    rejected: list[WeightingResult],
) -> str:
    """Build a human-readable summary of the conflict resolution decision."""
    if not rejected:
        source = preferred[0]
        return (
            f"Single source '{source.source.title}' selected as canonical "
            f"(weight {source.computed_weight:.3f}). No conflicts to resolve."
        )
    winner = preferred[0]
    parts = [
        (
            f"Source '{winner.source.title}' selected as canonical "
            f"(weight {winner.computed_weight:.3f})."
        ),
    ]
    parts.extend(
        f"Source '{loser.source.title}' rejected (weight {loser.computed_weight:.3f})."
        for loser in rejected
    )
    return " ".join(parts)


class HighestWeightConflictResolver:
    """Conflict resolver that selects the highest-weighted source.

    The source with the highest computed weight contributes its TEI fragment
    as the canonical content. All other sources are recorded as rejected with
    their weights and factor breakdowns preserved for audit and provenance.
    """

    async def resolve(  # noqa: PLR6301
        self,
        weighted_sources: list[WeightingResult],
    ) -> ConflictOutcome:
        """Resolve conflicts by selecting the highest-weighted source.

        Parameters
        ----------
        weighted_sources : list[WeightingResult]
            Sources with computed weights to resolve.

        Returns
        -------
        ConflictOutcome
            The merged canonical TEI and conflict resolution metadata.

        Raises
        ------
        ValueError
            If no weighted sources are provided.
        """
        if not weighted_sources:
            msg = "Cannot resolve conflicts with no sources."
            raise ValueError(msg)

        ranked = sorted(
            weighted_sources,
            key=lambda wr: wr.computed_weight,
            reverse=True,
        )
        winner = ranked[0]
        preferred = [winner]
        rejected = ranked[1:]

        return ConflictOutcome(
            merged_tei_xml=winner.source.tei_fragment,
            merged_title=winner.source.title,
            preferred_sources=preferred,
            rejected_sources=rejected,
            resolution_notes=_build_resolution_notes(preferred, rejected),
        )
