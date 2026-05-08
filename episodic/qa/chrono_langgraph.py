"""LangGraph seam for the Chrono spoken-runtime estimator."""

import dataclasses as dc
import typing as typ

from langgraph.graph import END, START, StateGraph

if typ.TYPE_CHECKING:
    from langgraph.graph.state import CompiledStateGraph

    from .chrono import ChronoEvaluationRequest, ChronoRuntimeEstimate
else:
    CompiledStateGraph = typ.Any
    ChronoEvaluationRequest = typ.Any
    ChronoRuntimeEstimate = typ.Any


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


def build_chrono_graph(
    evaluator: ChronoEvaluatorPort,
) -> CompiledStateGraph[ChronoGraphState, None, ChronoGraphState, ChronoGraphState]:
    """Build the minimal Chrono StateGraph used by the QA layer."""
    graph = StateGraph(ChronoGraphState)

    async def chrono_node(
        state: ChronoGraphState,
    ) -> dict[str, ChronoRuntimeEstimate]:
        if state.chrono_request is None:
            msg = "chrono_request"
            raise KeyError(msg)
        return {"chrono_result": await evaluator.evaluate(state.chrono_request)}

    graph.add_node("chrono", chrono_node)
    graph.add_edge(START, "chrono")
    graph.add_edge("chrono", END)
    return graph.compile()
