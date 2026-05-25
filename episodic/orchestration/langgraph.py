"""LangGraph wrapper for structured generation orchestration.

This module owns the in-process graph topology for structured content
generation. The default graph plans, executes, and aggregates results. When a
`CheckpointPort` is supplied, the graph switches to a suspend path that
persists the planned state before the side-effecting execution step and returns
a `SuspendedWorkflowResult`; `resume_generation_orchestration` later rebuilds
the saved planner state and folds in an externally supplied action result.
"""

import importlib
import time
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
from episodic.orchestration._types import _log_event
from episodic.orchestration._usage import build_generation_result

if typ.TYPE_CHECKING:
    import collections.abc as cabc

    from langgraph.graph.state import CompiledStateGraph

    from episodic.orchestration import _dto as dto
    from episodic.orchestration import _protocols as protocols
else:
    dto = importlib.import_module("episodic.orchestration._dto")
    protocols = importlib.import_module("episodic.orchestration._protocols")


type ExecuteNodeResult = (
    dict[str, tuple[dto.ActionExecutionResult, ...]]
    | dict[str, dto.SuspendedWorkflowResult]
)


class ExecuteNodeFn(typ.Protocol):
    """Callable protocol for async execute graph nodes."""

    def __call__(
        self, state: GenerationGraphState
    ) -> cabc.Awaitable[ExecuteNodeResult]:
        """Return the async execute-node update for *state*."""
        ...


async def _plan_node(
    state: GenerationGraphState,
    *,
    planner: protocols.PlannerPort,
) -> dict[str, dto.PlannerResult]:
    """Validate state and invoke the planner to produce a PlannerResult."""
    request = state.request
    correlation_id = request.correlation_id if request is not None else None
    _log_event(
        "debug",
        "generation_graph.plan_node.start",
        correlation_id=correlation_id,
    )
    if request is None:
        msg = "missing required state value: request"
        raise ValueError(msg)
    try:
        planner_result = await planner.plan(request)
    except Exception as exc:
        _log_event(
            "error",
            "generation_graph.plan_node.error",
            correlation_id=request.correlation_id,
            error=str(exc),
        )
        raise
    result = {"planner_result": planner_result}
    _log_event(
        "debug",
        "generation_graph.plan_node.finish",
        correlation_id=request.correlation_id,
    )
    return result


async def _execute_node(
    state: GenerationGraphState,
    *,
    tool_executor: protocols.ToolExecutorPort,
) -> dict[str, tuple[dto.ActionExecutionResult, ...]]:
    """Validate state and execute each planned action through the tool executor."""
    request = state.request
    correlation_id = request.correlation_id if request is not None else None
    _log_event(
        "debug",
        "generation_graph.execute_node.start",
        correlation_id=correlation_id,
    )
    if request is None:
        msg = "missing required state value: request"
        raise ValueError(msg)
    planner_result = state.planner_result
    if planner_result is None:
        msg = "missing required state value: planner_result"
        raise ValueError(msg)

    # Keep tool execution ordered so the graph mirrors application-service semantics.
    action_results: list[dto.ActionExecutionResult] = []
    for action in planner_result.plan.steps:
        started_at = time.monotonic()
        action_fields = {
            "correlation_id": request.correlation_id,
            "action_id": action.action_id,
            "action_kind": str(action.action_kind),
            "model_tier": str(action.model_tier),
            "execution_model": planner_result.plan.selected_execution_model,
        }
        try:
            action_result = await tool_executor.execute(action, request)
        except Exception as exc:
            _log_event(
                "error",
                "generation_graph.execute_node.action.error",
                **action_fields,
                elapsed_ms=round((time.monotonic() - started_at) * 1000, 1),
                error=str(exc),
            )
            raise
        action_fields["execution_model"] = action_result.model
        _log_event(
            "debug",
            "generation_graph.execute_node.action.finish",
            **action_fields,
            elapsed_ms=round((time.monotonic() - started_at) * 1000, 1),
        )
        action_results.append(action_result)
    result = {"action_results": tuple(action_results)}
    _log_event(
        "debug",
        "generation_graph.execute_node.finish",
        correlation_id=request.correlation_id,
    )
    return result


def _finish_node(
    state: GenerationGraphState,
) -> dict[str, dto.GenerationOrchestrationResult]:
    """Aggregate planner and action results into a GenerationOrchestrationResult."""
    request = state.request
    correlation_id = request.correlation_id if request is not None else None
    _log_event(
        "debug",
        "generation_graph.finish_node.start",
        correlation_id=correlation_id,
    )
    if request is None:
        msg = "missing required state value: request"
        raise ValueError(msg)
    planner_result = state.planner_result
    if planner_result is None:
        msg = "missing required state value: planner_result"
        raise ValueError(msg)
    try:
        orchestration_result = build_generation_result(
            planner_result,
            state.action_results,
        )
    except Exception as exc:
        _log_event(
            "error",
            "generation_graph.finish_node.error",
            correlation_id=correlation_id,
            error=str(exc),
        )
        raise
    result = {"orchestration_result": orchestration_result}
    _log_event(
        "debug",
        "generation_graph.finish_node.finish",
        correlation_id=correlation_id,
    )
    return result


def _invoke_finish_callback(
    finish_callback: cabc.Callable[[dto.GenerationOrchestrationResult], None],
    result: dict[str, dto.GenerationOrchestrationResult],
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
        finish_callback(result["orchestration_result"])
        _log_event(
            "debug",
            "generation_graph.finish_node.callback.finish",
            correlation_id=correlation_id,
        )
    except Exception as exc:  # noqa: BLE001
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
    checkpoint_port: protocols.CheckpointPort | None = None,
    finish_callback: cabc.Callable[[dto.GenerationOrchestrationResult], None]
    | None = None,
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
        checkpoint_port: Optional persistence port. When provided, the graph
            writes a checkpoint after planning and returns a suspended result
            instead of running the direct finish path.
        finish_callback: Optional callable invoked as
            `finish_callback(result)` after finish-node aggregation and before
            returning from the direct-execute path. It receives the
            `GenerationOrchestrationResult` produced by the finish node.
            Invoked only on the direct plan -> execute -> finish path, not
            the checkpoint suspend path. Callback exceptions are logged
            without replacing the computed graph result. The graph does not
            serialize concurrent invocations of the same callback; callbacks
            that mutate shared state must be thread-safe or otherwise
            synchronize their own state.
    """
    graph = StateGraph(GenerationGraphState)

    async def _run_plan_node(
        state: GenerationGraphState,
    ) -> dict[str, dto.PlannerResult]:
        """Async entry point for the plan graph node."""
        return await _plan_node(state, planner=planner)

    def _run_finish_node(
        state: GenerationGraphState,
    ) -> dict[str, dto.GenerationOrchestrationResult]:
        """Entry point for the finish graph node."""
        result = _finish_node(state)
        if finish_callback is not None:
            correlation_id = (
                state.request.correlation_id if state.request is not None else None
            )
            _invoke_finish_callback(finish_callback, result, correlation_id)
        return result

    execute_node, execute_target = _build_execute_node(tool_executor, checkpoint_port)

    graph.add_node("plan", _run_plan_node)
    graph.add_node("execute", execute_node)
    graph.add_node("finish", _run_finish_node)
    graph.add_edge(START, "plan")
    graph.add_edge("plan", "execute")
    graph.add_edge("execute", execute_target)
    graph.add_edge("finish", END)
    return graph.compile()
