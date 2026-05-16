"""LangGraph seam for the Chrono spoken-runtime estimator.

This module adapts Chrono's local runtime estimator to the orchestration shape
used by the QA layer. It keeps graph state and node wiring separate from the
deterministic estimation policy in ``episodic.qa.chrono``.

Main entry points:

- ``ChronoEvaluatorPort``: Protocol implemented by objects that can evaluate a
  ``ChronoEvaluationRequest`` asynchronously and return a
  ``ChronoRuntimeEstimate``.
- ``ChronoGraphState``: Minimal state object carrying the Chrono request and
  result through the graph.
- ``build_chrono_graph``: Builds a one-node ``StateGraph`` that validates the
  request, calls the evaluator, stores ``chrono_result``, and terminates.

Use this adapter when Chrono participates in LangGraph QA orchestration. Direct
callers that only need a spoken-runtime estimate should use
``ChronoRuntimeEstimator`` from ``episodic.qa.chrono`` instead. The graph seam
depends on the estimator port and result contracts, while the estimator module
remains independent of LangGraph.
"""

import dataclasses as dc
import logging
import typing as typ

from langgraph.graph import END, START, StateGraph

_log = logging.getLogger(__name__)

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
            _log.error(
                "Chrono graph node missing required request; has_chrono_result=%s",
                state.chrono_result is not None,
                extra={"has_chrono_result": state.chrono_result is not None},
            )
            msg = "chrono_request"
            raise KeyError(msg)
        try:
            result = await evaluator.evaluate(state.chrono_request)
        except Exception:
            _log.exception(
                "Chrono graph node evaluation failed; input_character_count=%s",
                len(state.chrono_request.script_tei_xml),
                extra={
                    "input_character_count": len(state.chrono_request.script_tei_xml)
                },
            )
            raise
        return {"chrono_result": result}

    graph.add_node("chrono", chrono_node)
    graph.add_edge(START, "chrono")
    graph.add_edge("chrono", END)
    return graph.compile()
