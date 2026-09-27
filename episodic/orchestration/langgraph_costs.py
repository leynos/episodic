"""Provider-call cost recording for the direct generation orchestration path.

This module records planner and action provider-call costs once the
generation graph's `finish` node has produced a result along the direct
(non-checkpointed) execution path. `_record_costs_from_finished_state` is
the entry point `langgraph.py` calls from the `finish` node; it pins run
pricing, records each provider call that carries usage, and finalizes the
workflow run.
"""

import importlib
import typing as typ

from episodic.orchestration._planning_orchestrator import (
    _cost_provider_operations,
    _current_billing_period_key,
    _provider_call_record,
    _ProviderCallContext,
)

if typ.TYPE_CHECKING:
    from episodic.cost import BillingPeriodKey, CostRecorderPort
    from episodic.orchestration import _dto as dto
    from episodic.orchestration._graph_state import GenerationGraphState
else:
    dto = importlib.import_module("episodic.orchestration._dto")


async def _record_planner_cost_if_available(
    cost_recorder: CostRecorderPort,
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
    cost_recorder: CostRecorderPort,
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
    cost_recorder: CostRecorderPort | None,
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
