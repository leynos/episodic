"""LangGraph wrapper for structured generation orchestration."""

from __future__ import annotations

import dataclasses as dc
import json
import typing as typ

from langgraph.graph import END, START, StateGraph

from episodic.logging import getLogger
from episodic.orchestration.generation import (
    ActionExecutionResult,
    GenerationOrchestrationRequest,
    GenerationOrchestrationResult,
    PlannerPort,
    PlannerResult,
    ToolExecutorPort,
    build_generation_result,
)

if typ.TYPE_CHECKING:
    from langgraph.graph.state import CompiledStateGraph


_log = getLogger(__name__)


def _log_event(level: str, message: str, **fields: object) -> None:
    """Emit one structured log event with a JSON fallback."""
    log_method = getattr(_log, level)
    try:
        log_method(message, **fields)
    except TypeError:
        payload = {"event": message, **fields}
        log_method(json.dumps(payload, sort_keys=True))


@dc.dataclass(slots=True)
class GenerationGraphState:
    """Typed graph state for initialize-plan-execute-finish orchestration."""

    request: GenerationOrchestrationRequest | None = None
    planner_result: PlannerResult | None = None
    action_results: tuple[ActionExecutionResult, ...] = ()
    orchestration_result: GenerationOrchestrationResult | None = None


async def _plan_node(
    state: GenerationGraphState,
    *,
    planner: PlannerPort,
) -> dict[str, PlannerResult]:
    """Validate state and invoke the planner to produce a PlannerResult."""
    request = state.request
    correlation_id = request.correlation_id if request is not None else None
    _log_event(
        "debug",
        "generation_graph.plan_node.start",
        correlation_id=correlation_id,
    )
    if request is None:
        msg = "request"
        raise KeyError(msg)
    result = {"planner_result": await planner.plan(request)}
    _log_event(
        "debug",
        "generation_graph.plan_node.finish",
        correlation_id=request.correlation_id,
    )
    return result


async def _execute_node(
    state: GenerationGraphState,
    *,
    tool_executor: ToolExecutorPort,
) -> dict[str, tuple[ActionExecutionResult, ...]]:
    """Validate state and execute each planned action through the tool executor."""
    request = state.request
    correlation_id = request.correlation_id if request is not None else None
    _log_event(
        "debug",
        "generation_graph.execute_node.start",
        correlation_id=correlation_id,
    )
    if request is None:
        msg = "request"
        raise KeyError(msg)
    planner_result = state.planner_result
    if planner_result is None:
        msg = "planner_result"
        raise KeyError(msg)

    # Keep tool execution ordered so the graph mirrors application-service semantics.
    action_results: list[ActionExecutionResult] = []
    for action in planner_result.plan.steps:
        action_results.append(  # noqa: PERF401
            await tool_executor.execute(action, request)
        )
    result = {"action_results": tuple(action_results)}
    _log_event(
        "debug",
        "generation_graph.execute_node.finish",
        correlation_id=request.correlation_id,
    )
    return result


def _finish_node(
    state: GenerationGraphState,
) -> dict[str, GenerationOrchestrationResult]:
    """Aggregate planner and action results into a GenerationOrchestrationResult."""
    correlation_id = state.request.correlation_id if state.request is not None else None
    _log_event(
        "debug",
        "generation_graph.finish_node.start",
        correlation_id=correlation_id,
    )
    planner_result = state.planner_result
    if planner_result is None:
        msg = "planner_result"
        raise KeyError(msg)
    result = {
        "orchestration_result": build_generation_result(
            planner_result,
            state.action_results,
        )
    }
    _log_event(
        "debug",
        "generation_graph.finish_node.finish",
        correlation_id=correlation_id,
    )
    return result


def build_generation_orchestration_graph(
    *,
    planner: PlannerPort,
    tool_executor: ToolExecutorPort,
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
    ) -> dict[str, PlannerResult]:
        """Async entry point for the plan graph node."""
        return await _plan_node(state, planner=planner)

    async def _run_execute_node(
        state: GenerationGraphState,
    ) -> dict[str, tuple[ActionExecutionResult, ...]]:
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
