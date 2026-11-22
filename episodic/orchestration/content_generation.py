"""LangGraph topology and runner for the content-generation graph.

The graph is compiled once and injected into the launcher through
:class:`~episodic.canonical.generation_graph_ports.ContentGenerationGraphPort`.
Node functions live in :mod:`episodic.orchestration._content_graph_nodes` and
import no framework; this module wraps each in a closure that supplies
``runtime.context``, so per-run collaborators reach nodes without the compiled
graph holding any run state.

The runner deliberately uses no ``step_timeout``, no subgraph, no
``stream_eager``, and no ``messages`` or ``custom`` stream mode. Each of those
would move node execution off the caller's task, breaking ordered event
publication and the single-writer rule (decision D2 and axiom AXM-1).
"""

import asyncio
import dataclasses as dc
import typing as typ

from langgraph.errors import NodeCancelledError
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime  # ruff: ignore[typing-only-third-party-import]  # Closure annotation is evaluated at definition.

from episodic.canonical.generation_graph_ports import (
    ContentGenerationGraphError,
    ContentGenerationRequest,
    ContentGenerationSteps,
    QualityEvaluatorSet,
)
from episodic.canonical.generation_quality import QualityMode
from episodic.canonical.generation_routing import (
    EvaluationRoute,
    GenerationTerminal,
    QualityBranch,
    branch_for_terminal,
    route_quality_mode,
)
from episodic.orchestration._content_graph_nodes import (
    escalate,
    evaluate,
    generate_draft_without_qa,
    generate_qa_candidate,
    initialize,
    persist_draft_without_qa,
    persist_qa_passed_draft,
    route_after_evaluate,
    route_after_initialize,
)
from episodic.orchestration._content_graph_state import (
    NODE_OWNERSHIP,
    ContentGenerationContext,
    ContentGenerationGraphState,
)

if typ.TYPE_CHECKING:
    import collections.abc as cabc

    from langgraph.graph.state import CompiledStateGraph

type ContentGenerationNode = cabc.Callable[
    [ContentGenerationGraphState, ContentGenerationContext],
    cabc.Awaitable[dict[str, object]],
]


class _WrappedNode(typ.Protocol):
    """Graph-callable node that receives LangGraph's runtime."""

    def __call__(
        self,
        state: ContentGenerationGraphState,
        runtime: Runtime[ContentGenerationContext],
    ) -> cabc.Awaitable[dict[str, object]]:
        """Execute the node with the run's context."""


_NODES: cabc.Mapping[str, ContentGenerationNode] = {
    "initialize": initialize,
    "generate_draft_without_qa": generate_draft_without_qa,
    "persist_draft_without_qa": persist_draft_without_qa,
    "generate_qa_candidate": generate_qa_candidate,
    "evaluate": evaluate,
    "persist_qa_passed_draft": persist_qa_passed_draft,
    "escalate": escalate,
}


def _wrap(node: ContentGenerationNode) -> _WrappedNode:
    """Wrap a plain node so LangGraph supplies its runtime context."""

    async def run(
        state: ContentGenerationGraphState,
        runtime: Runtime[ContentGenerationContext],
    ) -> dict[str, object]:
        """Execute the wrapped node with the run's context."""
        return await node(state, runtime.context)

    return run


def build_content_generation_graph() -> CompiledStateGraph[
    ContentGenerationGraphState,
    ContentGenerationContext,
    ContentGenerationGraphState,
    ContentGenerationGraphState,
]:
    """Build and compile the content-generation graph.

    Returns
    -------
    CompiledStateGraph[...]
        The compiled graph. Every branch owns its nodes and its terminal; only
        ``initialize`` is shared.
    """
    graph = StateGraph(
        ContentGenerationGraphState,
        context_schema=ContentGenerationContext,
    )
    for node_name in NODE_OWNERSHIP:
        graph.add_node(node_name, _wrap(_NODES[node_name]))
    graph.add_edge(START, "initialize")
    graph.add_conditional_edges(
        "initialize",
        route_after_initialize,
        path_map={
            QualityBranch.DRAFT_WITHOUT_QA: "generate_draft_without_qa",
            QualityBranch.QA_GATED: "generate_qa_candidate",
        },
    )
    graph.add_edge("generate_draft_without_qa", "persist_draft_without_qa")
    graph.add_edge("persist_draft_without_qa", END)
    graph.add_edge("generate_qa_candidate", "evaluate")
    graph.add_conditional_edges(
        "evaluate",
        route_after_evaluate,
        path_map={
            EvaluationRoute.PASS: "persist_qa_passed_draft",
            EvaluationRoute.ESCALATE: "escalate",
        },
    )
    graph.add_edge("persist_qa_passed_draft", END)
    graph.add_edge("escalate", END)
    return graph.compile()


@dc.dataclass(slots=True)
class LangGraphContentGenerationGraph:
    """Compiled content-generation graph bound to one evaluator set.

    Attributes
    ----------
    evaluator_set : QualityEvaluatorSet
        Evaluators every QA-gated run uses, and their timeout.
    """

    evaluator_set: QualityEvaluatorSet
    _compiled: CompiledStateGraph[
        ContentGenerationGraphState,
        ContentGenerationContext,
        ContentGenerationGraphState,
        ContentGenerationGraphState,
    ] = dc.field(init=False)

    def __post_init__(self) -> None:
        """Compile the graph once."""
        self._compiled = build_content_generation_graph()

    def accepted_quality_modes(self) -> frozenset[QualityMode]:
        """Return the quality modes this deployment can execute.

        The evaluator set owns the capability rule, and this method is the
        port's single source of truth for it.

        Returns
        -------
        frozenset[QualityMode]
            The quality modes this deployment can execute.
        """
        modes = self.evaluator_set.accepted_quality_modes()
        typ.assert_type(modes, frozenset[QualityMode])
        return modes

    async def run(
        self,
        request: ContentGenerationRequest,
        *,
        steps: ContentGenerationSteps,
    ) -> GenerationTerminal:
        """Execute one run and return the terminal it reached.

        Parameters
        ----------
        request : ContentGenerationRequest
            The run and the quality mode that selects its branch.
        steps : ContentGenerationSteps
            The run session through which nodes reach run state.

        Returns
        -------
        GenerationTerminal
            The terminal the run reached.

        Raises
        ------
        ContentGenerationGraphError
            If the graph ends without a terminal, or reaches a terminal owned
            by a branch other than the one the quality mode selects.
        asyncio.CancelledError
            If the run is cancelled, including a node that raised
            ``CancelledError`` itself. LangGraph wraps the latter in
            :class:`~langgraph.errors.NodeCancelledError`; the runner restores
            the cancellation so shutdown classification is unchanged.
        """
        try:
            result = await self._compiled.ainvoke(
                ContentGenerationGraphState(request=request),
                context=ContentGenerationContext(
                    steps=steps,
                    evaluator_set=self.evaluator_set,
                ),
            )
        except NodeCancelledError as exc:
            raise asyncio.CancelledError from exc
        terminal = _require_terminal(result)
        expected = route_quality_mode(request.quality_mode)
        if branch_for_terminal(terminal) is not expected:
            msg = (
                f"content generation graph reached {terminal.value!r} "
                f"while the run's branch is {expected.value!r}"
            )
            raise ContentGenerationGraphError(msg)
        return terminal


def _require_terminal(state: dict[str, object]) -> GenerationTerminal:
    """Return the terminal the final graph state recorded."""
    terminal = state.get("terminal")
    if not isinstance(terminal, GenerationTerminal):
        msg = "content generation graph ended without a terminal"
        raise ContentGenerationGraphError(msg)
    return terminal
