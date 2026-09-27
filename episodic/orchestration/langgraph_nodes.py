"""Graph node bodies for the generation orchestration LangGraph.

This module owns the `plan`, `execute`, and `finish` node implementations
that `langgraph.py` wires into the compiled `StateGraph`. Each node validates
the required state, delegates to the relevant port, and emits structured
log events around the call. `_invoke_finish_callback` runs the optional
finish callback supplied through `GenerationGraphExtensions` after the
`finish` node has produced its result.
"""

import importlib
import time
import typing as typ

from episodic.orchestration._graph_state import _require_request_and_planner
from episodic.orchestration._types import _log_event
from episodic.orchestration._usage import build_generation_result

if typ.TYPE_CHECKING:
    import collections.abc as cabc

    from episodic.orchestration import _dto as dto
    from episodic.orchestration import _protocols as protocols
    from episodic.orchestration._graph_state import GenerationGraphState
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


async def _execute_single_action(
    action: dto.PlannedAction,
    request: dto.GenerationOrchestrationRequest,
    *,
    tool_executor: protocols.ToolExecutorPort,
    selected_execution_model: str,
) -> dto.ActionExecutionResult:
    """Execute one planned action and emit diagnostic log events."""
    started_at = time.monotonic()
    action_fields = {
        "correlation_id": request.correlation_id,
        "action_id": action.action_id,
        "action_kind": str(action.action_kind),
        "model_tier": str(action.model_tier),
        "execution_model": selected_execution_model,
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
    return action_result


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
    request, planner_result = _require_request_and_planner(state)

    # Keep tool execution ordered so the graph mirrors application-service semantics.
    action_results = [
        await _execute_single_action(
            action,
            request,
            tool_executor=tool_executor,
            selected_execution_model=planner_result.plan.selected_execution_model,
        )
        for action in planner_result.plan.steps
    ]
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
    _, planner_result = _require_request_and_planner(state)
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
    except Exception as exc:  # noqa: BLE001  # Deliberately swallow callback failures to preserve the computed graph result.
        _log_event(
            "error",
            "generation_graph.finish_node.callback.error",
            correlation_id=correlation_id,
            error=str(exc),
        )
