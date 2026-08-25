"""LangGraph topology builder for generation orchestration."""

import dataclasses as dc
import importlib
import typing as typ

from langgraph.graph import END, START, StateGraph

from episodic.orchestration._checkpoint_resume import _suspend_execute_node
from episodic.orchestration._graph_nodes import (
    ExecuteNodeFn,
    _execute_node,
    _finish_node,
    _plan_node,
)
from episodic.orchestration._graph_state import GenerationGraphState
from episodic.orchestration.langgraph_costs import (
    _record_costs_from_finished_state,
)
from episodic.orchestration._types import _log_event

if typ.TYPE_CHECKING:
    import collections.abc as cabc

    from langgraph.graph.state import CompiledStateGraph

    from episodic.cost import CostRecorderPort
    from episodic.orchestration import _dto as dto
    from episodic.orchestration import _protocols as protocols
else:
    dto = importlib.import_module("episodic.orchestration._dto")
    protocols = importlib.import_module("episodic.orchestration._protocols")


@dc.dataclass(slots=True)
class GenerationGraphExtensions:
    """Optional collaborators for the generation orchestration graph.

    Attributes
    ----------
    checkpoint_port : CheckpointPort | None
        Persistence boundary used to suspend and resume graph execution.
    finish_callback : Callable[[GenerationOrchestrationResult], None] | None
        Optional callback invoked with the completed orchestration result.
    cost_recorder : CostRecorderPort | None
        Optional port used to persist provider-call cost records.
    """

    checkpoint_port: protocols.CheckpointPort | None = None
    finish_callback: cabc.Callable[[dto.GenerationOrchestrationResult], None] | None = (
        None
    )
    cost_recorder: CostRecorderPort | None = None


def _invoke_finish_callback(
    finish_callback: cabc.Callable[[dto.GenerationOrchestrationResult], None],
    result: dto.GenerationOrchestrationResult,
    correlation_id: str | None,
) -> None:
    """Invoke *finish_callback* with the aggregated domain result.

    Logs a debug event on success and an error event on failure.
    Exceptions are swallowed so that callback failures do not replace
    the already-computed graph result. The callback is invoked synchronously
    in the graph execution context; callbacks shared across concurrent graph
    invocations must provide their own synchronization.
    """
    try:
        finish_callback(result)
        _log_event(
            "debug",
            "generation_graph.finish_node.callback.finish",
            correlation_id=correlation_id,
        )
    except Exception as exc:  # ruff: ignore[blind-except]  # Callback failures must not replace a completed graph result.
        _log_event(
            "error",
            "generation_graph.finish_node.callback.error",
            correlation_id=correlation_id,
            error=str(exc),
        )


def _build_execute_node(
    tool_executor: protocols.ToolExecutorPort,
    checkpoint_port: protocols.CheckpointPort | None,
) -> tuple[ExecuteNodeFn, str]:
    """Return *(execute_node_fn, execute_target)* for the graph.

    When *checkpoint_port* is ``None``, returns the direct execute node
    targeting ``"finish"``. Otherwise returns the suspend-before-execute node
    targeting ``END``.

    Returns
    -------
        The execute node callable and its graph target.
    """
    if checkpoint_port is None:

        async def _run_execute_node(
            state: GenerationGraphState,
        ) -> dict[str, tuple[dto.ActionExecutionResult, ...]]:
            """Async entry point for the execute graph node."""
            return await _execute_node(state, tool_executor=tool_executor)

        return _run_execute_node, "finish"

    async def _run_suspend_execute_node(
        state: GenerationGraphState,
    ) -> dict[str, dto.SuspendedWorkflowResult]:
        """Async entry point for the suspend-before-execute graph node."""
        return await _suspend_execute_node(
            state,
            checkpoint_port=checkpoint_port,
        )

    return _run_suspend_execute_node, END


def build_generation_orchestration_graph(
    *,
    planner: protocols.PlannerPort,
    tool_executor: protocols.ToolExecutorPort,
    extensions: GenerationGraphExtensions | None = None,
) -> CompiledStateGraph[
    GenerationGraphState,
    None,
    GenerationGraphState,
    GenerationGraphState,
]:
    """Build the in-process generation orchestration graph.

    The returned graph plans a structured generation request, either executes
    the first planned action directly and aggregates a final
    `GenerationOrchestrationResult`, or suspends after planning when
    `checkpoint_port` is provided.

    Args:
        planner: Port used by the `plan` node to produce an execution plan.
        tool_executor: Port used by the direct `execute` node to run planned
            actions.
        extensions: Optional persistence, callback, and cost-recording
            collaborators for graph execution.

    Returns
    -------
        The compiled generation orchestration graph.
    """
    graph_extensions = extensions or GenerationGraphExtensions()
    graph = StateGraph(GenerationGraphState)

    async def _run_plan_node(
        state: GenerationGraphState,
    ) -> dict[str, dto.PlannerResult]:
        """Async entry point for the plan graph node."""
        return await _plan_node(state, planner=planner)

    async def _run_finish_node(
        state: GenerationGraphState,
    ) -> dict[str, dto.GenerationOrchestrationResult]:
        """Entry point for the finish graph node."""
        result = _finish_node(state)
        await _record_costs_from_finished_state(
            state, cost_recorder=graph_extensions.cost_recorder
        )
        if graph_extensions.finish_callback is not None:
            correlation_id = (
                state.request.correlation_id if state.request is not None else None
            )
            _invoke_finish_callback(
                graph_extensions.finish_callback,
                result["orchestration_result"],
                correlation_id,
            )
        return result

    execute_node, execute_target = _build_execute_node(
        tool_executor, graph_extensions.checkpoint_port
    )

    graph.add_node("plan", _run_plan_node)
    graph.add_node("execute", execute_node)
    graph.add_node("finish", _run_finish_node)
    graph.add_edge(START, "plan")
    graph.add_edge("plan", "execute")
    graph.add_edge("execute", execute_target)
    graph.add_edge("finish", END)
    return graph.compile()
