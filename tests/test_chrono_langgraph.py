"""Unit tests for Chrono's minimal LangGraph seam."""

import asyncio
import dataclasses as dc
import typing as typ

import pytest

from episodic.qa.chrono import (
    ChronoEstimatorMetadata,
    ChronoEvaluationRequest,
    ChronoRuntimeEstimate,
    ChronoRuntimeEstimator,
)
from episodic.qa.chrono_langgraph import (
    ChronoGraphState,
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


@dc.dataclass(slots=True)
class _FailingChronoEvaluator:
    """Raise a canned exception for graph observability tests."""

    error: Exception

    async def evaluate(
        self,
        request: ChronoEvaluationRequest,
    ) -> ChronoRuntimeEstimate:
        """Raise the canned error."""
        raise self.error


def _request() -> ChronoEvaluationRequest:
    return ChronoEvaluationRequest(
        script_tei_xml=(
            "<TEI><text><body><sp><p>Hello from Chrono.</p></sp></body></text></TEI>"
        )
    )


def _tei_document(body: str) -> str:
    """Wrap a TEI body fixture with the required document header."""
    return (
        "<TEI><teiHeader><fileDesc><title>Chrono graph test</title></fileDesc>"
        f"</teiHeader><text><body>{body}</body></text></TEI>"
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
    """Graph node should require a chrono_request in graph state."""
    evaluator = _FakeChronoEvaluator(_result())
    graph = build_chrono_graph(evaluator)

    with pytest.raises(KeyError, match="chrono_request"):
        await graph.ainvoke(ChronoGraphState())


@pytest.mark.asyncio
async def test_chrono_node_logs_missing_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Graph node should log context before raising for missing input."""
    evaluator = _FakeChronoEvaluator(_result())
    graph = build_chrono_graph(evaluator)
    errors: list[tuple[str, tuple[object, ...], dict[str, object]]] = []

    def capture_error(
        msg: str,
        *args: object,
        **kwargs: object,
    ) -> None:
        errors.append((msg, args, kwargs))

    monkeypatch.setattr("episodic.qa.chrono_langgraph._log.error", capture_error)
    with pytest.raises(KeyError, match="chrono_request"):
        await graph.ainvoke(ChronoGraphState())

    assert errors == [
        (
            "Chrono graph node missing required request; has_chrono_result=%s",
            (False,),
            {"extra": {"has_chrono_result": False}},
        )
    ]


@pytest.mark.asyncio
async def test_chrono_node_calls_evaluator_and_stores_result() -> None:
    """The graph node should call the evaluator and return a result delta."""
    request = _request()
    result = _result()
    evaluator = _FakeChronoEvaluator(result)
    graph = build_chrono_graph(evaluator)

    state = await graph.ainvoke(ChronoGraphState(chrono_request=request))

    assert evaluator.requests == [request]
    assert state["chrono_result"] == result


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


@pytest.mark.asyncio
async def test_chrono_node_logs_evaluation_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Graph node should log context before propagating evaluator failures."""
    graph = build_chrono_graph(_FailingChronoEvaluator(ValueError("bad TEI")))
    request = _request()
    exceptions: list[tuple[str, tuple[object, ...], dict[str, object]]] = []

    def capture_exception(
        msg: str,
        *args: object,
        **kwargs: object,
    ) -> None:
        exceptions.append((msg, args, kwargs))

    monkeypatch.setattr(
        "episodic.qa.chrono_langgraph._log.exception",
        capture_exception,
    )
    with pytest.raises(ValueError, match="bad TEI"):
        await graph.ainvoke(ChronoGraphState(chrono_request=request))

    assert exceptions == [
        (
            "Chrono graph node evaluation failed; input_character_count=%s",
            (len(request.script_tei_xml),),
            {"extra": {"input_character_count": len(request.script_tei_xml)}},
        )
    ]


@pytest.mark.asyncio
async def test_chrono_graph_handles_concurrent_invocations() -> None:
    """A shared graph and evaluator should keep concurrent state isolated."""
    evaluator = ChronoRuntimeEstimator()
    graph = build_chrono_graph(evaluator)
    requests = [
        ChronoEvaluationRequest(
            script_tei_xml=_tei_document(
                f"<sp><p>{' '.join(['word'] * (index + 1))}</p></sp>"
            )
        )
        for index in range(5)
    ]

    states = await asyncio.gather(
        *(
            graph.ainvoke(ChronoGraphState(chrono_request=request))
            for request in requests
        )
    )
    results = [
        typ.cast("ChronoRuntimeEstimate", state["chrono_result"]) for state in states
    ]

    assert results == [evaluator.estimate(request) for request in requests], (
        "concurrent graph invocations must match direct estimator results"
    )
    assert [result.metadata.input_character_count for result in results] == [
        len(request.script_tei_xml) for request in requests
    ], "concurrent graph invocations must preserve per-request metadata"
