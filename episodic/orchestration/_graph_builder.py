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
from episodic.orchestration._planning_orchestrator import (
    _cost_provider_operations,
    _current_billing_period_key,
    _provider_call_record,
    _ProviderCallContext,
)
from episodic.orchestration._types import _log_event

if typ.TYPE_CHECKING:
    import collections.abc as cabc

    from langgraph.graph.state import CompiledStateGraph

    from episodic.cost import BillingPeriodKey
    from episodic.orchestration import _dto as dto
    from episodic.orchestration import _protocols as protocols
else:
    dto = importlib.import_module("episodic.orchestration._dto")
    protocols = importlib.import_module("episodic.orchestration._protocols")


@dc.dataclass
class GenerationGraphExtensions:
    """Optional collaborators for the generation orchestration graph."""

    checkpoint_port: protocols.CheckpointPort | None = None
    finish_callback: cabc.Callable[[dto.GenerationOrchestrationResult], None] | None = (
        None
    )
    cost_recorder: protocols.CostRecorderPort | None = None


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


async def _record_planner_cost_if_available(
    cost_recorder: protocols.CostRecorderPort,
    *,
    workflow_run_id: str,
    planner_result: dto.PlannerResult,
    billing_period_key: BillingPeriodKey,
) -> None:
    """Record a planner provider-call cost entry when usage is available."""
    if planner_result.provider_call_usage is None:
        return
    await cost_recorder.record_provider_call(
        _provider_call_record(
            context=_ProviderCallContext(
                workflow_run_id=workflow_run_id,
                workflow_node="planner",
                logical_call_id=planner_result.provider_response_id,
                model=planner_result.model,
                operation=str(planner_result.provider_operation),
            ),
            provider_call_usage=planner_result.provider_call_usage,
            billing_period_key=billing_period_key,
        )
    )


async def _record_action_costs_from_results(
    cost_recorder: protocols.CostRecorderPort,
    *,
    workflow_run_id: str,
    action_results: tuple[dto.ActionExecutionResult, ...],
    billing_period_key: BillingPeriodKey,
) -> None:
    """Record a provider-call cost entry for each action result that carries usage."""
    for action_result in action_results:
        if action_result.provider_call_usage is None:
            continue
        await cost_recorder.record_provider_call(
            _provider_call_record(
                context=_ProviderCallContext(
                    workflow_run_id=workflow_run_id,
                    workflow_node=action_result.action_kind.value,
                    logical_call_id=action_result.action_id,
                    model=action_result.model,
                    operation=str(action_result.provider_operation),
                ),
                provider_call_usage=action_result.provider_call_usage,
                billing_period_key=billing_period_key,
            )
        )


async def _record_costs_from_finished_state(
    state: GenerationGraphState,
    *,
    cost_recorder: protocols.CostRecorderPort | None,
) -> None:
    """Record graph provider-call costs from the finished direct path."""
    if cost_recorder is None:
        return
    if state.request is None or state.planner_result is None:
        return
    billing_period_key = _current_billing_period_key()
    planner_result = state.planner_result
    workflow_run_id = state.request.correlation_id
    providers = _cost_provider_operations(planner_result)
    if providers:
        await cost_recorder.pin_run_pricing(
            workflow_run_id, providers, billing_period_key
        )
    await _record_planner_cost_if_available(
        cost_recorder,
        workflow_run_id=workflow_run_id,
        planner_result=planner_result,
        billing_period_key=billing_period_key,
    )
    await _record_action_costs_from_results(
        cost_recorder,
        workflow_run_id=workflow_run_id,
        action_results=state.action_results,
        billing_period_key=billing_period_key,
    )
    await cost_recorder.finalize_run(workflow_run_id, None)


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
