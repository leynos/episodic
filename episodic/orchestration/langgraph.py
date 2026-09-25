"""LangGraph wrapper for structured generation orchestration.

This module owns the in-process graph topology for structured content
generation. The default graph plans, executes, and aggregates results. When a
`CheckpointPort` is supplied, the graph switches to a suspend path that
persists the planned state before the side-effecting execution step and returns
a `SuspendedWorkflowResult`; `resume_generation_orchestration` later rebuilds
the saved planner state and folds in an externally supplied action result.

Node bodies live in `langgraph_nodes.py` and direct-path cost recording
lives in `langgraph_costs.py`; this module assembles them into the compiled
`StateGraph`.
"""

import dataclasses as dc
import importlib
import typing as typ

from langgraph.graph import END, START, StateGraph

from episodic.orchestration._checkpoint_payload import (
    _action_result_from_payload as _action_result_from_payload,
)
from episodic.orchestration._checkpoint_payload import (
    _action_result_to_payload as _action_result_to_payload,
)
from episodic.orchestration._checkpoint_payload import (
    _plan_from_payload as _plan_from_payload,
)
from episodic.orchestration._checkpoint_payload import (
    _plan_to_payload as _plan_to_payload,
)
from episodic.orchestration._checkpoint_payload import (
    _planner_result_from_payload as _planner_result_from_payload,
)
from episodic.orchestration._checkpoint_payload import (
    _planner_result_to_payload as _planner_result_to_payload,
)
from episodic.orchestration._checkpoint_payload import (
    _usage_from_payload as _usage_from_payload,
)
from episodic.orchestration._checkpoint_payload import (
    _usage_to_payload as _usage_to_payload,
)
from episodic.orchestration._checkpoint_resume import (
    _suspend_execute_node as _suspend_execute_node,
)
from episodic.orchestration._checkpoint_resume import (
    _validate_suspend_preconditions as _validate_suspend_preconditions,
)
from episodic.orchestration._checkpoint_resume import (
    resume_generation_orchestration as resume_generation_orchestration,
)
from episodic.orchestration._graph_state import GenerationGraphState
from episodic.orchestration.langgraph_costs import (
    _record_costs_from_finished_state,
)
from episodic.orchestration.langgraph_nodes import (
    ExecuteNodeFn,
    _execute_node,
    _finish_node,
    _invoke_finish_callback,
    _plan_node,
)

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
    """Optional collaborators for the generation orchestration graph."""

    checkpoint_port: protocols.CheckpointPort | None = None
    finish_callback: cabc.Callable[[dto.GenerationOrchestrationResult], None] | None = (
        None
    )
    cost_recorder: CostRecorderPort | None = None


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
    tuple[ExecuteNodeFn, str]
        The execute-node callable and its graph target. The target is
        ``"finish"`` for direct execution or ``END`` for checkpoint
        suspension.
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
    CompiledStateGraph
        The compiled orchestration graph containing the ``plan``, ``execute``,
        and ``finish`` nodes.
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
                graph_extensions.finish_callback, result, correlation_id
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
