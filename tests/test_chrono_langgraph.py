"""Unit tests for Chrono's minimal LangGraph seam."""

import dataclasses as dc
import typing as typ

import pytest

from episodic.qa.chrono import (
    ChronoEstimatorMetadata,
    ChronoEvaluationRequest,
    ChronoRuntimeEstimate,
)
from episodic.qa.chrono_langgraph import (
    ChronoGraphState,
    _chrono_node,
    build_chrono_graph,
)


@dc.dataclass(slots=True)
class _FakeChronoEvaluator:
    """Return one canned Chrono estimate."""

    result: ChronoRuntimeEstimate
    requests: list[ChronoEvaluationRequest] = dc.field(default_factory=list)

    async def evaluate(
        self,
        request: ChronoEvaluationRequest,
    ) -> ChronoRuntimeEstimate:
        """Return the canned result after capturing the request."""
        self.requests.append(request)
        return self.result


def _request() -> ChronoEvaluationRequest:
    return ChronoEvaluationRequest(
        script_tei_xml=(
            "<TEI><text><body><sp><p>Hello from Chrono.</p></sp></body></text></TEI>"
        )
    )


def _result() -> ChronoRuntimeEstimate:
    return ChronoRuntimeEstimate(
        estimated_seconds=2,
        metadata=ChronoEstimatorMetadata(
            estimator_name="chrono-naive-word-count",
            estimator_version="1",
            input_character_count=75,
            spoken_word_count=3,
            words_per_minute=150,
        ),
    )


@pytest.mark.asyncio
async def test_chrono_node_requires_chrono_request() -> None:
    """_chrono_node should require a chrono_request in graph state."""
    evaluator = _FakeChronoEvaluator(_result())

    with pytest.raises(KeyError, match="chrono_request"):
        await _chrono_node(ChronoGraphState(), evaluator=evaluator)


@pytest.mark.asyncio
async def test_chrono_node_calls_evaluator_and_stores_result() -> None:
    """The graph node should call the evaluator and return a result delta."""
    request = _request()
    result = _result()
    evaluator = _FakeChronoEvaluator(result)

    delta = await _chrono_node(
        ChronoGraphState(chrono_request=request),
        evaluator=evaluator,
    )

    assert evaluator.requests == [request]
    assert delta == {"chrono_result": result}


@pytest.mark.asyncio
async def test_chrono_graph_propagates_result_and_metadata() -> None:
    """Graph should propagate Chrono's local estimate and metadata."""
    result = _result()
    graph = build_chrono_graph(_FakeChronoEvaluator(result))

    state = await graph.ainvoke(ChronoGraphState(chrono_request=_request()))
    chrono_result = typ.cast("ChronoRuntimeEstimate", state["chrono_result"])

    assert chrono_result.estimated_seconds == 2
    assert chrono_result.metadata.estimator_name == "chrono-naive-word-count"
    assert chrono_result.metadata.spoken_word_count == 3
    assert not hasattr(chrono_result, "usage")
