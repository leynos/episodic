"""Reference weighting strategy adapter.

This adapter computes source weights as a weighted average of quality,
freshness, and reliability scores using coefficients from the series
configuration or sensible defaults.

Examples
--------
Compute weights for normalised sources:

>>> strategy = DefaultWeightingStrategy()
>>> results = await strategy.compute_weights(sources, config)
>>> results[0].computed_weight
0.87
"""

from __future__ import annotations

import typing as typ

from episodic.canonical.adapters._coercion import coerce_float
from episodic.canonical.ingestion import NormalisedSource, WeightingResult

if typ.TYPE_CHECKING:
    from episodic.canonical.domain import JsonMapping

#: Default weighting coefficients when series configuration is absent.
_DEFAULT_QUALITY_COEFFICIENT = 0.5
_DEFAULT_FRESHNESS_COEFFICIENT = 0.3
_DEFAULT_RELIABILITY_COEFFICIENT = 0.2


def _extract_coefficients(
    series_configuration: JsonMapping,
) -> tuple[float, float, float]:
    """Extract weighting coefficients from series configuration.

    The configuration may contain a ``"weighting"`` dictionary with
    ``"quality_coefficient"``, ``"freshness_coefficient"``, and
    ``"reliability_coefficient"`` keys. Missing keys fall back to defaults.
    """
    weighting = series_configuration.get("weighting")
    if not isinstance(weighting, dict):
        return (
            _DEFAULT_QUALITY_COEFFICIENT,
            _DEFAULT_FRESHNESS_COEFFICIENT,
            _DEFAULT_RELIABILITY_COEFFICIENT,
        )
    weighting_map = typ.cast("dict[str, object]", weighting)
    quality = coerce_float(
        weighting_map.get("quality_coefficient"),
        _DEFAULT_QUALITY_COEFFICIENT,
    )
    freshness = coerce_float(
        weighting_map.get("freshness_coefficient"),
        _DEFAULT_FRESHNESS_COEFFICIENT,
    )
    reliability = coerce_float(
        weighting_map.get("reliability_coefficient"),
        _DEFAULT_RELIABILITY_COEFFICIENT,
    )
    return (quality, freshness, reliability)


def _compute_single_weight(
    source: NormalisedSource,
    quality_coeff: float,
    freshness_coeff: float,
    reliability_coeff: float,
) -> WeightingResult:
    """Compute the weighted average for a single normalised source."""
    raw_weight = (
        source.quality_score * quality_coeff
        + source.freshness_score * freshness_coeff
        + source.reliability_score * reliability_coeff
    )
    computed = max(0.0, min(1.0, raw_weight))
    factors: JsonMapping = {
        "quality_score": source.quality_score,
        "freshness_score": source.freshness_score,
        "reliability_score": source.reliability_score,
        "quality_coefficient": quality_coeff,
        "freshness_coefficient": freshness_coeff,
        "reliability_coefficient": reliability_coeff,
        "raw_weight": raw_weight,
    }
    return WeightingResult(
        source=source,
        computed_weight=computed,
        factors=factors,
    )


class DefaultWeightingStrategy:
    """Reference weighting strategy using a weighted average.

    The weight for each source is computed as::

        weight = quality * q_coeff + freshness * f_coeff + reliability * r_coeff

    Coefficients are read from the series configuration under the
    ``"weighting"`` key, falling back to defaults (quality=0.5, freshness=0.3,
    reliability=0.2) when absent. Results are clamped to [0, 1].
    """

    async def compute_weights(  # noqa: PLR6301
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
        quality_coeff, freshness_coeff, reliability_coeff = _extract_coefficients(
            series_configuration,
        )
        return [
            _compute_single_weight(
                source,
                quality_coeff,
                freshness_coeff,
                reliability_coeff,
            )
            for source in sources
        ]
