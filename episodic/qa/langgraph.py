"""LangGraph seam for the Pedante evaluator."""

from __future__ import annotations

import dataclasses as dc
import typing as typ

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph  # noqa: TC002

from .pedante import (  # noqa: TC001
    PedanteEvaluationRequest,
    PedanteEvaluationResult,
)


class PedanteEvaluatorPort(typ.Protocol):
    """Protocol for Pedante evaluators used by orchestration code."""

    async def evaluate(
        self,
        request: PedanteEvaluationRequest,
    ) -> PedanteEvaluationResult:
        """Evaluate a script and return claim-level findings."""
        ...


@dc.dataclass(slots=True)
class PedanteGraphState:
    """Minimal Pedante graph state used by the current QA seam."""

    pedante_request: PedanteEvaluationRequest | None = None
    pedante_result: PedanteEvaluationResult | None = None


async def _pedante_node(
    state: PedanteGraphState,
    *,
    evaluator: PedanteEvaluatorPort,
) -> dict[str, PedanteEvaluationResult]:
    """Run Pedante and return the state delta."""
    if state.pedante_request is None:
        msg = "pedante_request"
        raise KeyError(msg)
    return {"pedante_result": await evaluator.evaluate(state.pedante_request)}


def route_after_pedante(state: PedanteGraphState) -> typ.Literal["pass", "refine"]:
    """Route supported scripts to pass and blocking findings to refine.

    The routing decision is derived solely from ``pedante_result.requires_revision``
    to keep routing logic centralised and avoid divergence with other state.
    """
    if state.pedante_result is None:
        msg = "pedante_result"
        raise KeyError(msg)
    return "refine" if state.pedante_result.requires_revision else "pass"


def build_pedante_graph(
    evaluator: PedanteEvaluatorPort,
) -> CompiledStateGraph[
    PedanteGraphState,
    None,
    PedanteGraphState,
    PedanteGraphState,
]:
    """Build the minimal Pedante StateGraph used by the QA layer."""
    graph = StateGraph(PedanteGraphState)

    async def _run_pedante_node(
        state: PedanteGraphState,
    ) -> dict[str, PedanteEvaluationResult]:
        return await _pedante_node(state, evaluator=evaluator)

    graph.add_node("pedante", _run_pedante_node)
    graph.add_edge(START, "pedante")
    graph.add_conditional_edges(
        "pedante",
        route_after_pedante,
        {
            "pass": END,
            "refine": END,
        },
    )
    return graph.compile()
