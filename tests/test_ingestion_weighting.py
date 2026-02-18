"""Unit tests for weighting strategy adapters."""

from __future__ import annotations

import pytest
from _ingestion_service_helpers import _make_normalised_source

from episodic.canonical.adapters.weighting import DefaultWeightingStrategy


@pytest.fixture
def weighting_strategy() -> DefaultWeightingStrategy:
    """Provide a weighting strategy instance for adapter tests."""
    return DefaultWeightingStrategy()


@pytest.mark.asyncio
async def test_weighting_strategy_computes_weighted_average(
    weighting_strategy: DefaultWeightingStrategy,
) -> None:
    """The strategy computes weights as a weighted average with defaults."""
    source = _make_normalised_source(
        quality=0.9,
        freshness=0.8,
        reliability=0.9,
    )

    results = await weighting_strategy.compute_weights([source], {})

    assert len(results) == 1, "Expected one weighting result for one input source."
    assert results[0].computed_weight == pytest.approx(0.87), (
        "Expected weighted average to use default coefficients."
    )
    assert "quality_coefficient" in results[0].factors, (
        "Expected factor breakdown to include quality coefficient."
    )
    assert results[0].factors["quality_coefficient"] == pytest.approx(0.5), (
        "Expected default quality coefficient to be recorded."
    )


@pytest.mark.asyncio
async def test_weighting_strategy_respects_series_configuration(
    weighting_strategy: DefaultWeightingStrategy,
) -> None:
    """Custom coefficients from series configuration are used."""
    source = _make_normalised_source(
        quality=1.0,
        freshness=0.0,
        reliability=0.0,
    )
    config = {
        "weighting": {
            "quality_coefficient": 1.0,
            "freshness_coefficient": 0.0,
            "reliability_coefficient": 0.0,
        },
    }

    results = await weighting_strategy.compute_weights([source], config)

    assert results[0].computed_weight == pytest.approx(1.0), (
        "Expected custom coefficients in configuration to drive weighting."
    )


@pytest.mark.asyncio
async def test_weighting_strategy_clamps_to_unit_interval(
    weighting_strategy: DefaultWeightingStrategy,
) -> None:
    """Weights are clamped to [0, 1] even with extreme scores."""
    source = _make_normalised_source(
        quality=2.0,
        freshness=2.0,
        reliability=2.0,
    )

    results = await weighting_strategy.compute_weights([source], {})

    assert results[0].computed_weight <= 1.0, (
        "Expected computed weights to be clamped to the upper bound."
    )
    assert results[0].computed_weight >= 0.0, (
        "Expected computed weights to be clamped to the lower bound."
    )
