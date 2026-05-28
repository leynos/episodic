"""Unit tests for weighting strategy adapters."""

import dataclasses as dc
import typing as typ

import pytest
from _ingestion_service_helpers import _make_normalized_source

from episodic.canonical.adapters.weighting import DefaultWeightingStrategy

if typ.TYPE_CHECKING:
    import collections.abc as cabc

    from episodic.canonical.domain import JsonMapping

_InputT = typ.TypeVar("_InputT")
_OutputT = typ.TypeVar("_OutputT")


class RecordingCpuTaskExecutor:
    """Test double that records how many map dispatches occurred."""

    def __init__(self) -> None:
        self.map_calls = 0

    async def map_ordered(
        self,
        task: cabc.Callable[[_InputT], _OutputT],
        items: tuple[_InputT, ...],
    ) -> list[_OutputT]:
        """Map inputs and record invocation count for assertions."""
        self.map_calls += 1
        return [task(item) for item in items]


@dc.dataclass(slots=True)
class _RecordingCpuTaskExecutorMetrics:
    """Capture executor selection metrics for composition-root wiring tests."""

    counters: list[tuple[str, dict[str, str]]] = dc.field(default_factory=list)

    def increment_counter(
        self,
        name: str,
        *,
        labels: cabc.Mapping[str, str],
    ) -> None:
        """Record a counter increment."""
        self.counters.append((name, dict(labels)))

    def observe_latency_ms(
        self,
        name: str,
        value: float,
        *,
        labels: cabc.Mapping[str, str],
    ) -> None:
        """Record a latency observation."""

    def observe_value(
        self,
        name: str,
        value: float,
        *,
        labels: cabc.Mapping[str, str],
    ) -> None:
        """Record a scalar observation."""


@pytest.fixture
def weighting_strategy() -> DefaultWeightingStrategy:
    """Provide a weighting strategy instance for adapter tests."""
    return DefaultWeightingStrategy()


@pytest.mark.asyncio
async def test_weighting_strategy_computes_weighted_average(
    weighting_strategy: DefaultWeightingStrategy,
) -> None:
    """The strategy computes weights as a weighted average with defaults."""
    source = _make_normalized_source(
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
    source = _make_normalized_source(
        quality=1.0,
        freshness=0.0,
        reliability=0.0,
    )
    config: JsonMapping = {
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
    source = _make_normalized_source(
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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("min_parallel_items", "source_scores", "expected_map_calls", "expected_weights"),
    [
        (
            2,
            (
                (0.8, 0.7, 0.9),
                (0.7, 0.8, 0.6),
            ),
            1,
            [0.79, 0.71],
        ),
        (
            3,
            ((0.8, 0.7, 0.9),),
            0,
            [0.79],
        ),
    ],
    ids=["uses_executor_at_threshold", "skips_executor_below_threshold"],
)
async def test_weighting_strategy_threshold_dispatch(
    min_parallel_items: int,
    source_scores: tuple[tuple[float, float, float], ...],
    expected_map_calls: int,
    expected_weights: list[float],
) -> None:
    """Threshold controls executor dispatch while preserving correct outputs."""
    recording_executor = RecordingCpuTaskExecutor()
    strategy = DefaultWeightingStrategy(
        cpu_executor=recording_executor,
        min_parallel_items=min_parallel_items,
    )
    sources = [
        _make_normalized_source(
            quality=quality,
            freshness=freshness,
            reliability=reliability,
        )
        for quality, freshness, reliability in source_scores
    ]

    results = await strategy.compute_weights(sources, {})

    assert len(results) == len(expected_weights), (
        "Expected one weighting result per input source."
    )
    assert recording_executor.map_calls == expected_map_calls, (
        "Expected threshold configuration to control executor dispatch."
    )
    assert [result.computed_weight for result in results] == pytest.approx(
        expected_weights,
    ), "Expected deterministic computed weights for both dispatch paths."


def test_default_weighting_strategy_forwards_metrics_to_executor_builder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Composition roots can wire executor metrics through the strategy."""
    metrics = _RecordingCpuTaskExecutorMetrics()
    captured: dict[str, object] = {}

    def fake_build_cpu_task_executor_from_environment(
        environ: cabc.Mapping[str, str],
        *,
        metrics: object = None,
    ) -> RecordingCpuTaskExecutor:
        captured["metrics"] = metrics
        return RecordingCpuTaskExecutor()

    monkeypatch.setattr(
        "episodic.canonical.adapters.weighting.build_cpu_task_executor_from_environment",
        fake_build_cpu_task_executor_from_environment,
    )

    DefaultWeightingStrategy(metrics=metrics)

    assert captured["metrics"] is metrics, (
        "Expected strategy construction to forward metrics to the executor builder."
    )
