"""Behaviour tests for the structured planning orchestrator.

These tests document how `StructuredPlanningOrchestrator` connects the
structured planner port, tool-executor port, and generation result aggregation
helpers. They give CI visibility into the orchestration contract: plans are
produced by `StructuredGenerationPlanner`, actions are dispatched through a
tool adapter, show-notes tool output is preserved, and planner/action usage is
rolled up into the final `GenerationOrchestrationResult`.
"""

import json
import typing as typ

import pytest

from episodic.cost.ports import CostLedgerEntryId, UsageSource
from episodic.llm.ports import ProviderCallUsage
from episodic.orchestration import (
    ActionExecutionResult,
    ActionKind,
    ModelTier,
    PlannedAction,
    RoutingToolExecutor,
    ShowNotesFormatError,
    ShowNotesToolExecutor,
    StructuredGenerationPlanner,
    StructuredPlanningOrchestrator,
    ToolExecutionError,
)
from episodic.orchestration._action_result_dto import PlannerResult
from tests._orchestration_fakes import (
    _config,
    _FakeLLMPort,
    _FakeToolExecutor,
    _plan_payload,
    _request,
    _response,
    _usage,
)

if typ.TYPE_CHECKING:
    from episodic.cost.recorder import ProviderCallRecord


class _RecordingCostRecorder:
    """Capture cost-recorder calls made by the orchestrator."""

    def __init__(self) -> None:
        self.pinned_runs: list[tuple[str, object, object]] = []
        self.provider_calls: list[ProviderCallRecord] = []
        self.finalized_runs: list[tuple[str, str | None]] = []

    async def pin_run_pricing(
        self,
        workflow_run_id: str,
        providers: object,
        billing_period_key: object,
    ) -> None:
        """Record a run-pricing pin request."""
        self.pinned_runs.append((workflow_run_id, providers, billing_period_key))

    async def record_provider_call(
        self,
        record: ProviderCallRecord,
    ) -> CostLedgerEntryId:
        """Record one provider-call request."""
        self.provider_calls.append(record)
        return CostLedgerEntryId(f"entry-{len(self.provider_calls)}")

    async def finalize_run(
        self,
        workflow_run_id: str,
        workflow_node: str | None,
    ) -> CostLedgerEntryId:
        """Record one run-finalization request."""
        self.finalized_runs.append((workflow_run_id, workflow_node))
        return CostLedgerEntryId("rollup-entry")


class _FakePlanner:
    """Return a planner result with provider-call usage metadata."""

    def __init__(self, result: PlannerResult) -> None:
        self.result = result

    async def plan(self, request: object) -> PlannerResult:
        """Return the canned planner result."""
        return self.result


def _provider_call_usage(
    *,
    input_tokens: int,
    output_tokens: int,
    provider_response_id: str,
) -> ProviderCallUsage:
    return ProviderCallUsage(
        usage_metrics={
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
        },
        usage_source=UsageSource.PROVIDER,
        usage_complete=True,
        provider_response_id=provider_response_id,
        finish_reason="stop",
        started_at="2026-06-04T12:00:00+00:00",
        latency_ms=25,
    )


@pytest.mark.asyncio
async def test_orchestrator_dispatches_through_tool_port() -> None:
    """Orchestrator should execute planned actions via the tool port only."""
    llm = _FakeLLMPort([
        _response(
            _plan_payload(),
            model="gpt-4.1",
            usage=_usage(input_tokens=20, output_tokens=10),
        )
    ])
    planner = StructuredGenerationPlanner(llm=llm, config=_config())
    tool_result = ActionExecutionResult(
        action_id="action-1",
        action_kind=ActionKind.GENERATE_SHOW_NOTES,
        model_tier=ModelTier.EXECUTION,
        model="gpt-4o-mini",
        summary="Generated one show-notes payload.",
        usage=_usage(input_tokens=12, output_tokens=8),
    )
    tool_executor = _FakeToolExecutor(result=tool_result)
    orchestrator = StructuredPlanningOrchestrator(
        planner=planner,
        tool_executor=tool_executor,
    )

    result = await orchestrator.orchestrate(_request())

    assert len(tool_executor.calls) == 1
    planned_action, context = tool_executor.calls[0]
    assert planned_action.action_kind is ActionKind.GENERATE_SHOW_NOTES
    assert context.correlation_id == "corr-123"
    assert result.action_results == (tool_result,)
    assert result.total_usage == _usage(input_tokens=32, output_tokens=18)


@pytest.mark.asyncio
async def test_orchestrator_records_cost_entries_when_recorder_is_present() -> None:
    """Cost recording should be a side channel around the existing result."""
    planner_usage = _provider_call_usage(
        input_tokens=20,
        output_tokens=10,
        provider_response_id="planner-response",
    )
    plan = StructuredGenerationPlanner(
        llm=_FakeLLMPort([
            _response(
                _plan_payload(),
                model="gpt-4.1",
                usage=_usage(input_tokens=20, output_tokens=10),
            )
        ]),
        config=_config(),
    )
    planner_result = await plan.plan(_request())
    planner = _FakePlanner(
        PlannerResult(
            plan=planner_result.plan,
            usage=planner_result.usage,
            model="gpt-4.1",
            provider_response_id="planner-response",
            finish_reason="stop",
            provider_call_usage=planner_usage,
        )
    )
    tool_usage = _provider_call_usage(
        input_tokens=12,
        output_tokens=8,
        provider_response_id="tool-response",
    )
    tool_result = ActionExecutionResult(
        action_id="action-1",
        action_kind=ActionKind.GENERATE_SHOW_NOTES,
        model_tier=ModelTier.EXECUTION,
        model="gpt-4o-mini",
        summary="Generated one show-notes payload.",
        usage=_usage(input_tokens=12, output_tokens=8),
        provider_call_usage=tool_usage,
    )
    cost_recorder = _RecordingCostRecorder()
    orchestrator = StructuredPlanningOrchestrator(
        planner=planner,
        tool_executor=_FakeToolExecutor(result=tool_result),
        cost_recorder=cost_recorder,
    )

    result = await orchestrator.orchestrate(_request())

    assert result.total_usage == _usage(input_tokens=32, output_tokens=18)
    assert len(cost_recorder.pinned_runs) == 1
    assert cost_recorder.pinned_runs[0][0] == "corr-123"
    assert len(cost_recorder.provider_calls) == 2
    assert cost_recorder.finalized_runs == [("corr-123", None)]
    assert cost_recorder.provider_calls[0].workflow_node == "planner"
    assert cost_recorder.provider_calls[0].model == "gpt-4.1"
    assert cost_recorder.provider_calls[0].usage == planner_usage.usage_metrics
    assert cost_recorder.provider_calls[1].workflow_node == "generate_show_notes"
    assert cost_recorder.provider_calls[1].model == "gpt-4o-mini"
    assert cost_recorder.provider_calls[1].usage == tool_usage.usage_metrics


@pytest.mark.asyncio
async def test_orchestrator_aggregates_show_notes_tool_output() -> None:
    """Orchestrator should aggregate real show-notes tool output and usage."""
    planner_llm = _FakeLLMPort([
        _response(
            _plan_payload(),
            model="gpt-4.1",
            usage=_usage(input_tokens=20, output_tokens=10),
        )
    ])
    show_notes_llm = _FakeLLMPort([
        _response(
            json.dumps({
                "entries": [
                    {
                        "topic": "Structured planning",
                        "summary": "The hosts explain typed orchestration outputs.",
                        "timestamp": "PT5M30S",
                        "tei_locator": "#structured-planning",
                    }
                ]
            }),
            model="gpt-4o-mini",
            usage=_usage(input_tokens=18, output_tokens=7),
        )
    ])
    planner = StructuredGenerationPlanner(llm=planner_llm, config=_config())
    tool_executor = ShowNotesToolExecutor(llm=show_notes_llm, config=_config())
    orchestrator = StructuredPlanningOrchestrator(
        planner=planner,
        tool_executor=tool_executor,
    )

    result = await orchestrator.orchestrate(_request())

    assert result.plan.plan_version == "1.0"
    assert result.planner_usage == _usage(input_tokens=20, output_tokens=10)
    assert result.total_usage == _usage(input_tokens=38, output_tokens=17)
    assert len(result.action_results) == 1

    action_result = result.action_results[0]
    assert action_result.action_kind is ActionKind.GENERATE_SHOW_NOTES
    assert action_result.show_notes_result is not None
    assert action_result.show_notes_result.usage == _usage(
        input_tokens=18,
        output_tokens=7,
    )
    assert action_result.show_notes_result.entries[0].tei_locator == (
        "#structured-planning"
    )
    assert show_notes_llm.requests[0].model == "gpt-4o-mini"
    assert "template_structure" in show_notes_llm.requests[0].prompt


@pytest.mark.asyncio
async def test_orchestrator_propagates_show_notes_format_errors() -> None:
    """Malformed show-notes output should fail the orchestration run clearly."""
    planner_llm = _FakeLLMPort([
        _response(
            _plan_payload(),
            model="gpt-4.1",
            usage=_usage(input_tokens=20, output_tokens=10),
        )
    ])
    show_notes_llm = _FakeLLMPort([
        _response(
            json.dumps({"entries": [{"topic": "Missing summary"}]}),
            model="gpt-4o-mini",
            usage=_usage(input_tokens=18, output_tokens=7),
        )
    ])
    planner = StructuredGenerationPlanner(llm=planner_llm, config=_config())
    tool_executor = ShowNotesToolExecutor(llm=show_notes_llm, config=_config())
    orchestrator = StructuredPlanningOrchestrator(
        planner=planner,
        tool_executor=tool_executor,
    )

    with pytest.raises(
        ShowNotesFormatError,
        match="malformed structured JSON",
    ) as exc_info:
        await orchestrator.orchestrate(_request())

    assert exc_info.value.__cause__ is not None
    assert "summary" in str(exc_info.value.__cause__)
    assert len(show_notes_llm.requests) == 1


@pytest.mark.asyncio
async def test_orchestrator_propagates_tool_failures() -> None:
    """Tool errors should not be swallowed by the orchestration layer."""
    llm = _FakeLLMPort([
        _response(
            _plan_payload(),
            model="gpt-4.1",
            usage=_usage(input_tokens=20, output_tokens=10),
        )
    ])
    planner = StructuredGenerationPlanner(llm=llm, config=_config())
    tool_executor = _FakeToolExecutor(error=ToolExecutionError("tool exploded"))
    orchestrator = StructuredPlanningOrchestrator(
        planner=planner,
        tool_executor=tool_executor,
    )

    with pytest.raises(ToolExecutionError, match="tool exploded"):
        await orchestrator.orchestrate(_request())


@pytest.mark.asyncio
async def test_routing_tool_executor_dispatches_by_action_kind() -> None:
    """Routing executor should let one orchestration run support multiple tools."""
    show_notes_result = ActionExecutionResult(
        action_id="show-notes-1",
        action_kind=ActionKind.GENERATE_SHOW_NOTES,
        model_tier=ModelTier.EXECUTION,
        model="gpt-4o-mini",
        summary="Generated show notes.",
        usage=_usage(input_tokens=4, output_tokens=2),
    )
    guest_bios_result = ActionExecutionResult(
        action_id="guest-bios-1",
        action_kind=ActionKind.GENERATE_GUEST_BIOS,
        model_tier=ModelTier.EXECUTION,
        model="gpt-4o-mini",
        summary="Generated guest bios.",
        usage=_usage(input_tokens=6, output_tokens=3),
    )
    show_notes_executor = _FakeToolExecutor(result=show_notes_result)
    guest_bios_executor = _FakeToolExecutor(result=guest_bios_result)
    routing_executor = RoutingToolExecutor(
        routes={
            ActionKind.GENERATE_SHOW_NOTES: show_notes_executor,
            ActionKind.GENERATE_GUEST_BIOS: guest_bios_executor,
        }
    )
    request = _request()

    show_notes_action = PlannedAction(
        action_id="show-notes-1",
        action_kind=ActionKind.GENERATE_SHOW_NOTES,
        rationale="Need show notes.",
        model_tier=ModelTier.EXECUTION,
    )
    guest_bios_action = PlannedAction(
        action_id="guest-bios-1",
        action_kind=ActionKind.GENERATE_GUEST_BIOS,
        rationale="Need guest bios.",
        model_tier=ModelTier.EXECUTION,
    )

    assert (
        await routing_executor.execute(show_notes_action, request) == show_notes_result
    )
    assert (
        await routing_executor.execute(guest_bios_action, request) == guest_bios_result
    )
    assert show_notes_executor.calls == [(show_notes_action, request)]
    assert guest_bios_executor.calls == [(guest_bios_action, request)]


def test_routing_tool_executor_rejects_normalized_action_kind_collisions() -> None:
    """Routing executor should not silently discard equivalent route keys."""
    first_executor = _FakeToolExecutor()
    second_executor = _FakeToolExecutor()

    with pytest.raises(ValueError, match="route action kind collision"):
        RoutingToolExecutor(
            routes={
                "generate_show_notes": first_executor,
                " generate_show_notes ": second_executor,
            }
        )
