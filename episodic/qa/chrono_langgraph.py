"""LangGraph seam for the Chrono spoken-runtime estimator."""

from __future__ import annotations

import dataclasses as dc
import typing as typ

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph  # noqa: TC002

from .chrono import (  # noqa: TC001
    ChronoEvaluationRequest,
    ChronoRuntimeEstimate,
)


class ChronoEvaluatorPort(typ.Protocol):
    """Protocol for Chrono evaluators used by orchestration code."""

    async def evaluate(
        self,
        request: ChronoEvaluationRequest,
    ) -> ChronoRuntimeEstimate:
        """Estimate script runtime and return metadata."""
        ...


@dc.dataclass(slots=True)
class ChronoGraphState:
    """Minimal Chrono graph state used by the QA layer."""

    chrono_request: ChronoEvaluationRequest | None = None
    chrono_result: ChronoRuntimeEstimate | None = None


async def _chrono_node(
    state: ChronoGraphState,
    *,
    evaluator: ChronoEvaluatorPort,
) -> dict[str, ChronoRuntimeEstimate]:
    """Run Chrono and return the state delta."""
    if state.chrono_request is None:
        msg = "chrono_request"
        raise KeyError(msg)
    return {"chrono_result": await evaluator.evaluate(state.chrono_request)}


def build_chrono_graph(
    evaluator: ChronoEvaluatorPort,
) -> CompiledStateGraph[
    ChronoGraphState,
    None,
    ChronoGraphState,
    ChronoGraphState,
]:
    """Build the minimal Chrono StateGraph used by the QA layer."""
    graph = StateGraph(ChronoGraphState)

    async def _run_chrono_node(
        state: ChronoGraphState,
    ) -> dict[str, ChronoRuntimeEstimate]:
        return await _chrono_node(state, evaluator=evaluator)

    graph.add_node("chrono", _run_chrono_node)
    graph.add_edge(START, "chrono")
    graph.add_edge("chrono", END)
    return graph.compile()
