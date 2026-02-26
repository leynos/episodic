"""Reference weighting strategy adapter.

This adapter computes source weights as a weighted average of quality,
freshness, and reliability scores using coefficients from the series
configuration or sensible defaults.

Examples
--------
Compute weights for normalized sources:

>>> strategy = DefaultWeightingStrategy()
>>> results = await strategy.compute_weights(sources, config)
>>> results[0].computed_weight
0.87
"""

import functools
import os
import typing as typ

from episodic.canonical.adapters._coercion import coerce_float
from episodic.canonical.ingestion import NormalizedSource, WeightingResult
from episodic.concurrent_interpreters import (
    CpuTaskExecutor,
    build_cpu_task_executor_from_environment,
)

if typ.TYPE_CHECKING:
    from episodic.canonical.domain import JsonMapping

#: Default weighting coefficients when series configuration is absent.
_DEFAULT_QUALITY_COEFFICIENT = 0.5
_DEFAULT_FRESHNESS_COEFFICIENT = 0.3
_DEFAULT_RELIABILITY_COEFFICIENT = 0.2
_DEFAULT_INTERPRETER_POOL_MIN_ITEMS = 64
_INTERPRETER_POOL_MIN_ITEMS_ENV = "EPISODIC_INTERPRETER_POOL_MIN_ITEMS"


def _parse_min_parallel_items(raw_value: str | None) -> int:
    """Parse minimum batch size before interpreter execution is attempted."""
    if raw_value is None:
        return _DEFAULT_INTERPRETER_POOL_MIN_ITEMS
    try:
        parsed = int(raw_value)
    except ValueError:
        return _DEFAULT_INTERPRETER_POOL_MIN_ITEMS
    return max(1, parsed)


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
    source: NormalizedSource,
    quality_coeff: float,
    freshness_coeff: float,
    reliability_coeff: float,
) -> WeightingResult:
    """Compute the weighted average for a single normalized source."""
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

    def __init__(
        self,
        *,
        cpu_executor: CpuTaskExecutor | None = None,
        min_parallel_items: int | None = None,
    ) -> None:
        self._cpu_executor = (
            cpu_executor
            if cpu_executor is not None
            else build_cpu_task_executor_from_environment()
        )
        if min_parallel_items is None:
            self._min_parallel_items = _parse_min_parallel_items(
                os.getenv(_INTERPRETER_POOL_MIN_ITEMS_ENV),
            )
        else:
            self._min_parallel_items = max(1, min_parallel_items)

    async def compute_weights(
        self,
        sources: list[NormalizedSource],
        series_configuration: JsonMapping,
    ) -> list[WeightingResult]:
        """Compute weights for normalized sources.

        Parameters
        ----------
        sources : list[NormalizedSource]
            Normalized sources to weight.
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
        if len(sources) < self._min_parallel_items:
            return [
                _compute_single_weight(
                    source=source,
                    quality_coeff=quality_coeff,
                    freshness_coeff=freshness_coeff,
                    reliability_coeff=reliability_coeff,
                )
                for source in sources
            ]

        compute_with_coefficients = functools.partial(
            _compute_single_weight,
            quality_coeff=quality_coeff,
            freshness_coeff=freshness_coeff,
            reliability_coeff=reliability_coeff,
        )
        return await self._cpu_executor.map_ordered(
            compute_with_coefficients,
            tuple(sources),
        )
