"""LangGraph wrapper for structured generation orchestration."""

import dataclasses as dc
import importlib
import time
import typing as typ

from langgraph.graph import END, START, StateGraph

from episodic.orchestration._types import _log_event
from episodic.orchestration._usage import build_generation_result

if typ.TYPE_CHECKING:
    from langgraph.graph.state import CompiledStateGraph

    from episodic.orchestration import _dto as dto
    from episodic.orchestration import _protocols as protocols
else:
    dto = importlib.import_module("episodic.orchestration._dto")
    protocols = importlib.import_module("episodic.orchestration._protocols")


@dc.dataclass(slots=True)
class GenerationGraphState:
    """Typed graph state for initialize-plan-execute-finish orchestration."""

    request: dto.GenerationOrchestrationRequest | None = None
    planner_result: dto.PlannerResult | None = None
    action_results: tuple[dto.ActionExecutionResult, ...] = ()
    orchestration_result: dto.GenerationOrchestrationResult | None = None


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


def build_generation_orchestration_graph(
    *,
    planner: protocols.PlannerPort,
    tool_executor: protocols.ToolExecutorPort,
) -> CompiledStateGraph[
    GenerationGraphState,
    None,
    GenerationGraphState,
    GenerationGraphState,
]:
    """Build the minimal in-process generation orchestration graph."""
    graph = StateGraph(GenerationGraphState)

    async def _run_plan_node(
        state: GenerationGraphState,
    ) -> dict[str, dto.PlannerResult]:
        """Async entry point for the plan graph node."""
        return await _plan_node(state, planner=planner)

    async def _run_execute_node(
        state: GenerationGraphState,
    ) -> dict[str, tuple[dto.ActionExecutionResult, ...]]:
        """Async entry point for the execute graph node."""
        return await _execute_node(state, tool_executor=tool_executor)

    graph.add_node("plan", _run_plan_node)
    graph.add_node("execute", _run_execute_node)
    graph.add_node("finish", _finish_node)
    graph.add_edge(START, "plan")
    graph.add_edge("plan", "execute")
    graph.add_edge("execute", "finish")
    graph.add_edge("finish", END)
    return graph.compile()
