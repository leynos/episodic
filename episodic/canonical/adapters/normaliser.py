"""Reference source normaliser adapter.

This adapter normalises raw source content into minimal valid TEI XML
fragments using the tei-rapporteur library. Quality, freshness, and
reliability scores are assigned based on configurable source type defaults.

Examples
--------
Normalise a transcript source:

>>> normaliser = InMemorySourceNormaliser()
>>> result = await normaliser.normalise(raw_source)
>>> result.quality_score
0.9
"""

from __future__ import annotations

import dataclasses as dc
import typing as typ

import tei_rapporteur as _tei

from episodic.canonical.domain import SourceDocumentInput
from episodic.canonical.ingestion import NormalisedSource, RawSourceInput

if typ.TYPE_CHECKING:
    from episodic.canonical.domain import JsonMapping


@dc.dataclass(frozen=True, slots=True)
class _SourceTypeScores:
    """Default quality, freshness, and reliability scores for a source type."""

    quality: float
    freshness: float
    reliability: float


#: Default score profiles for known source types.
_DEFAULT_SCORES: dict[str, _SourceTypeScores] = {
    "transcript": _SourceTypeScores(quality=0.9, freshness=0.8, reliability=0.9),
    "brief": _SourceTypeScores(quality=0.8, freshness=0.7, reliability=0.8),
    "rss": _SourceTypeScores(quality=0.6, freshness=1.0, reliability=0.5),
    "press_release": _SourceTypeScores(quality=0.7, freshness=0.6, reliability=0.7),
    "research_notes": _SourceTypeScores(quality=0.5, freshness=0.5, reliability=0.6),
}

#: Fallback scores for unrecognized source types.
_FALLBACK_SCORES = _SourceTypeScores(quality=0.5, freshness=0.5, reliability=0.5)


def _infer_title(raw_source: RawSourceInput) -> str:
    """Infer a title from raw source content or metadata."""
    title = raw_source.metadata.get("title")
    if isinstance(title, str) and title.strip():
        return title.strip()
    # Fall back to the first non-blank line of content.
    for line in raw_source.content.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped[:120]
    return raw_source.source_type.replace("_", " ").title()


def _build_tei_xml(title: str) -> str:
    """Build minimal valid TEI XML from a title.

    This is a placeholder implementation that constructs a TEI document
    containing only the title.  Raw source content is **not** embedded in
    the fragment; a production normaliser should parse or transform the
    content into TEI body elements.
    """
    document = _tei.Document(title)
    return _tei.emit_xml(document)


def _build_source_document_input(
    raw_source: RawSourceInput,
    computed_weight: float,
) -> SourceDocumentInput:
    """Build a persistence-ready source document input from raw source."""
    return SourceDocumentInput(
        source_type=raw_source.source_type,
        source_uri=raw_source.source_uri,
        weight=computed_weight,
        content_hash=raw_source.content_hash,
        metadata=raw_source.metadata,
    )


class InMemorySourceNormaliser:
    """Reference normaliser that converts raw sources into TEI fragments.

    Scores are assigned from a configurable mapping of source type to
    quality, freshness, and reliability defaults. Unrecognized source types
    receive mid-range fallback scores.

    Parameters
    ----------
    score_overrides : dict[str, dict[str, float]] | None
        Optional per-source-type score overrides. Each entry maps a source
        type string to a dictionary with ``"quality"``, ``"freshness"``,
        and ``"reliability"`` float values.
    """

    def __init__(
        self,
        score_overrides: dict[str, JsonMapping] | None = None,
    ) -> None:
        self._scores = dict(_DEFAULT_SCORES)
        if score_overrides:
            for source_type, overrides in score_overrides.items():
                self._scores[source_type] = _SourceTypeScores(
                    quality=float(overrides.get("quality", 0.5)),
                    freshness=float(overrides.get("freshness", 0.5)),
                    reliability=float(overrides.get("reliability", 0.5)),
                )

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
            Normalised source with TEI fragment and quality scores.
        """
        scores = self._scores.get(raw_source.source_type, _FALLBACK_SCORES)
        title = _infer_title(raw_source)
        tei_fragment = _build_tei_xml(title)

        # Weight placeholder; the weighting strategy computes the final weight.
        source_input = _build_source_document_input(raw_source, 0.0)

        return NormalisedSource(
            source_input=source_input,
            title=title,
            tei_fragment=tei_fragment,
            quality_score=scores.quality,
            freshness_score=scores.freshness,
            reliability_score=scores.reliability,
        )
