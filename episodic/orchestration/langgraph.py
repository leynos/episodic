"""LangGraph wrapper for structured generation orchestration."""

from __future__ import annotations

import dataclasses as dc
import typing as typ

from langgraph.graph import END, START, StateGraph

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
    request = state.request
    if request is None:
        msg = "request"
        raise KeyError(msg)
    return {"planner_result": await planner.plan(request)}


async def _execute_node(
    state: GenerationGraphState,
    *,
    tool_executor: ToolExecutorPort,
) -> dict[str, tuple[ActionExecutionResult, ...]]:
    request = state.request
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
    return {"action_results": tuple(action_results)}


def _finish_node(
    state: GenerationGraphState,
) -> dict[str, GenerationOrchestrationResult]:
    planner_result = state.planner_result
    if planner_result is None:
        msg = "planner_result"
        raise KeyError(msg)
    return {
        "orchestration_result": build_generation_result(
            planner_result,
            state.action_results,
        )
    }


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
        return await _plan_node(state, planner=planner)

    async def _run_execute_node(
        state: GenerationGraphState,
    ) -> dict[str, tuple[ActionExecutionResult, ...]]:
        return await _execute_node(state, tool_executor=tool_executor)

    graph.add_node("plan", _run_plan_node)
    graph.add_node("execute", _run_execute_node)
    graph.add_node("finish", _finish_node)
    graph.add_edge(START, "plan")
    graph.add_edge("plan", "execute")
    graph.add_edge("execute", "finish")
    graph.add_edge("finish", END)
    return graph.compile()
