"""Behavioural tests for structured generation orchestration."""

from __future__ import annotations

import asyncio  # noqa: TC003  # pytest-bdd inspects step annotations at runtime.
import dataclasses as dc
import subprocess  # noqa: S404 - required to start a local Vidai Mock test server
import typing as typ
from pathlib import (
    Path,  # noqa: TC003  # pytest-bdd inspects step annotations at runtime.
)

import pytest
from pytest_bdd import given, scenario, then, when

from episodic.cost.ports import BillingPeriodKey, CostLedgerEntryId
from episodic.llm.openai_adapter import (
    OpenAICompatibleLLMAdapter,
    OpenAICompatibleLLMConfig,
)
from episodic.orchestration import (
    ActionKind,
    GenerationGraphState,
    GenerationOrchestrationConfig,
    GenerationOrchestrationRequest,
    InMemoryCheckpointStore,
    ResumeWorkflowCommand,
    ShowNotesToolExecutor,
    StructuredGenerationPlanner,
    StructuredPlanningOrchestrator,
    build_generation_orchestration_graph,
    resume_generation_orchestration,
)
from tests.steps.generation_orchestration_vidaimock import (
    find_free_port,
    start_vidaimock_process,
    write_provider_config,
    write_response_template,
)

if typ.TYPE_CHECKING:
    import collections.abc as cabc

    from episodic.cost.recorder import CostProviderOperation, ProviderCallRecord
    from episodic.llm.ports import LLMPort, LLMRequest, LLMResponse
    from episodic.orchestration import (
        ActionExecutionResult,
        GenerationOrchestrationResult,
        SuspendedWorkflowResult,
    )


@dc.dataclass(slots=True)
class OrchestrationBDDContext:
    """Shared state between orchestration BDD steps."""

    process: subprocess.Popen[str] | None = None
    base_url: str = ""
    request: GenerationOrchestrationRequest | None = None
    result: GenerationOrchestrationResult | None = None
    requests: list[LLMRequest] = dc.field(default_factory=list)
    suspended_result: SuspendedWorkflowResult | None = None
    repeated_suspended_result: SuspendedWorkflowResult | None = None
    cost_recorder: _RecordingCostRecorder | None = None


@dc.dataclass(slots=True)
class _RecordingLLMPort:
    """Capture the actual `LLMRequest` values before delegating."""

    wrapped: LLMPort
    requests: list[LLMRequest] = dc.field(default_factory=list)

    async def generate(self, request: LLMRequest) -> LLMResponse:
        """Record and forward the request."""
        self.requests.append(request)
        return await self.wrapped.generate(request)


@dc.dataclass(slots=True)
class _BDDResumePort:
    """Return the action result supplied by the behavioural resume command."""

    async def resume(
        self,
        command: ResumeWorkflowCommand,
    ) -> ActionExecutionResult:
        """Return the externally supplied action result."""
        return command.result


@dc.dataclass(slots=True)
class _RecordingCostRecorder:
    """Capture orchestration cost-recorder calls for the BDD scenario."""

    pinned_providers: tuple[CostProviderOperation, ...] = ()
    pinned_billing_period_key: BillingPeriodKey | None = None
    provider_calls: list[ProviderCallRecord] = dc.field(default_factory=list)
    finalized_workflow_run_id: str | None = None

    async def pin_run_pricing(
        self,
        workflow_run_id: str,
        providers: tuple[CostProviderOperation, ...],
        billing_period_key: BillingPeriodKey,
    ) -> None:
        """Capture pricing pins selected for this workflow."""
        _ = workflow_run_id
        self.pinned_providers = providers
        self.pinned_billing_period_key = billing_period_key

    async def record_provider_call(
        self,
        record: ProviderCallRecord,
    ) -> CostLedgerEntryId:
        """Capture provider-call ledger input."""
        self.provider_calls.append(record)
        return CostLedgerEntryId(f"bdd:{record.idempotency_key}")

    async def finalize_run(
        self,
        workflow_run_id: str,
        workflow_node: str | None,
    ) -> CostLedgerEntryId:
        """Capture the final run-level roll-up request."""
        _ = workflow_node
        self.finalized_workflow_run_id = workflow_run_id
        return CostLedgerEntryId(f"bdd:run:{workflow_run_id}:rollup")


def _run_async_step(
    runner: asyncio.Runner,
    step_fn: cabc.Callable[[], cabc.Awaitable[None]],
) -> None:
    """Execute an async BDD step via the provided runner."""
    runner.run(step_fn())


@pytest.fixture
def orchestration_context() -> cabc.Iterator[OrchestrationBDDContext]:
    """Share state between BDD steps and stop Vidai Mock afterward."""
    ctx = OrchestrationBDDContext()
    yield ctx
    if ctx.process is not None:
        ctx.process.terminate()
        try:
            ctx.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            ctx.process.kill()
            ctx.process.wait(timeout=5)


@scenario(
    "../features/generation_orchestration.feature",
    "Orchestrator plans a structured generation run and executes show notes",
)
def test_generation_orchestration_behaviour() -> None:
    """Run the structured generation orchestration scenario."""


@scenario(
    "../features/generation_orchestration.feature",
    "LangGraph suspends and resumes a structured generation run",
)
def test_generation_orchestration_suspend_resume_behaviour() -> None:
    """Run the resumable generation orchestration scenario."""


@given("a Vidai Mock orchestration server is running")
def vidaimock_server(
    orchestration_context: OrchestrationBDDContext,
    tmp_path: Path,
) -> None:
    """Start a local Vidai Mock instance for the orchestration flow."""
    provider_dir = tmp_path / "providers"
    template_dir = tmp_path / "templates" / "orchestration"
    provider_dir.mkdir(parents=True)
    template_dir.mkdir(parents=True)

    write_provider_config(provider_dir)
    write_response_template(template_dir)
    start_vidaimock_process(orchestration_context, tmp_path, port=find_free_port())


@given("a generation orchestration request is prepared")
def prepare_request(orchestration_context: OrchestrationBDDContext) -> None:
    """Create the generation request used by the orchestration scenario."""
    orchestration_context.request = GenerationOrchestrationRequest(
        correlation_id="bdd-correlation",
        script_tei_xml=(
            "<TEI><text><body><p>Welcome to episode 42.</p>"
            "<p>We discuss the main topic.</p></body></text></TEI>"
        ),
        template_structure={"sections": ["intro", "discussion"]},
    )


@when("the orchestration service plans and executes the request")
def run_orchestration(
    _function_scoped_runner: asyncio.Runner,
    orchestration_context: OrchestrationBDDContext,
) -> None:
    """Call the orchestration service with a live LLM adapter."""

    async def _orchestrate() -> None:
        request = orchestration_context.request
        if request is None:
            msg = "generation request was not prepared"
            raise AssertionError(msg)

        async with OpenAICompatibleLLMAdapter(
            config=OpenAICompatibleLLMConfig(
                base_url=orchestration_context.base_url,
                api_key="test-key",
            ),
        ) as adapter:
            recording_port = _RecordingLLMPort(wrapped=adapter)
            config = GenerationOrchestrationConfig(
                planning_model="gpt-4.1",
                execution_model="gpt-4o-mini",
            )
            cost_recorder = _RecordingCostRecorder()
            orchestrator = StructuredPlanningOrchestrator(
                planner=StructuredGenerationPlanner(
                    llm=recording_port,
                    config=config,
                ),
                tool_executor=ShowNotesToolExecutor(
                    llm=recording_port,
                    config=config,
                ),
                cost_recorder=cost_recorder,
            )

            orchestration_context.result = await orchestrator.orchestrate(request)
            orchestration_context.requests = recording_port.requests
            orchestration_context.cost_recorder = cost_recorder

    _run_async_step(_function_scoped_runner, _orchestrate)


@when(
    "the LangGraph orchestration service suspends before execution and resumes "
    "the request"
)
def run_suspend_resume_orchestration(
    _function_scoped_runner: asyncio.Runner,
    orchestration_context: OrchestrationBDDContext,
) -> None:
    """Call the checkpointing LangGraph flow with a live LLM adapter."""

    async def _orchestrate() -> None:  # noqa: PLR0914
        request = orchestration_context.request
        if request is None:
            msg = "generation request was not prepared"
            raise AssertionError(msg)

        async with OpenAICompatibleLLMAdapter(
            config=OpenAICompatibleLLMConfig(
                base_url=orchestration_context.base_url,
                api_key="test-key",
            ),
        ) as adapter:
            recording_port = _RecordingLLMPort(wrapped=adapter)
            config = GenerationOrchestrationConfig(
                planning_model="gpt-4.1",
                execution_model="gpt-4o-mini",
            )
            planner = StructuredGenerationPlanner(llm=recording_port, config=config)
            tool_executor = ShowNotesToolExecutor(llm=recording_port, config=config)
            checkpoint_store = InMemoryCheckpointStore()
            graph = build_generation_orchestration_graph(
                planner=planner,
                tool_executor=tool_executor,
                checkpoint_port=checkpoint_store,
            )

            first_state = await graph.ainvoke(GenerationGraphState(request=request))
            second_state = await graph.ainvoke(GenerationGraphState(request=request))
            suspended_result = first_state["suspended_result"]
            checkpoint = await checkpoint_store.get(suspended_result.checkpoint_id)
            if checkpoint is None:
                msg = "checkpoint was not persisted"
                raise AssertionError(msg)

            planner_result = first_state["planner_result"]
            action = planner_result.plan.steps[0]
            action_result = await tool_executor.execute(action, request)
            orchestration_context.result = await resume_generation_orchestration(
                checkpoint_port=checkpoint_store,
                resume_port=_BDDResumePort(),
                command=ResumeWorkflowCommand(
                    checkpoint_id=suspended_result.checkpoint_id,
                    result=action_result,
                ),
            )
            orchestration_context.suspended_result = suspended_result
            orchestration_context.repeated_suspended_result = second_state[
                "suspended_result"
            ]
            orchestration_context.requests = recording_port.requests

    _run_async_step(_function_scoped_runner, _orchestrate)


@then("the orchestration result includes a structured plan and show-notes output")
def assert_result(orchestration_context: OrchestrationBDDContext) -> None:
    """Verify the orchestration result exposes the plan and action output."""
    result = orchestration_context.result
    assert result is not None, "Expected orchestration result, got None."
    assert result.plan.plan_version == "1.0"
    assert result.plan.steps[0].action_kind is ActionKind.GENERATE_SHOW_NOTES
    assert result.action_results[0].show_notes_result is not None
    assert result.action_results[0].show_notes_result.entries[0].topic == "Introduction"
    assert result.total_usage.total_tokens == 81


@then("the orchestration requests use planning and execution models in order")
def assert_requests(orchestration_context: OrchestrationBDDContext) -> None:
    """Verify the planner call happens before the execution-stage tool call."""
    requests = orchestration_context.requests
    expected_models = ["gpt-4.1", "gpt-4o-mini"]
    if orchestration_context.suspended_result is not None:
        expected_models = ["gpt-4.1", "gpt-4.1", "gpt-4o-mini"]
    assert [request.model for request in requests] == expected_models
    assert "enabled_action_kinds" in requests[0].prompt
    assert "script_tei_xml" in requests[-1].prompt


@then(
    "the cost ledger includes planner and show-notes entries totalled into "
    "a task roll-up"
)
def assert_cost_ledger(orchestration_context: OrchestrationBDDContext) -> None:
    """Verify the BDD flow records the billable planner and executor calls."""
    result = orchestration_context.result
    request = orchestration_context.request
    recorder = orchestration_context.cost_recorder
    assert result is not None, "Expected orchestration result, got None."
    assert request is not None, "Expected orchestration request, got None."
    assert recorder is not None, "Expected injected cost recorder, got None."
    assert recorder.pinned_billing_period_key is not None
    assert [provider.model for provider in recorder.pinned_providers] == [
        "gpt-4.1",
        "gpt-4o-mini",
    ]
    assert [record.workflow_node for record in recorder.provider_calls] == [
        "planner",
        "generate_show_notes",
    ]
    assert [record.model for record in recorder.provider_calls] == [
        "gpt-4.1",
        "gpt-4o-mini",
    ]
    assert [record.usage for record in recorder.provider_calls] == [
        {"input_tokens": 41, "output_tokens": 13},
        {"input_tokens": 19, "output_tokens": 8},
    ]
    assert sum(sum(record.usage.values()) for record in recorder.provider_calls) == (
        result.total_usage.total_tokens
    )
    assert recorder.finalized_workflow_run_id == request.correlation_id


@then("the orchestration checkpoint is reused for the repeated workflow step")
def assert_checkpoint_reused(orchestration_context: OrchestrationBDDContext) -> None:
    """Verify repeated suspend calls return the original checkpoint."""
    first = orchestration_context.suspended_result
    second = orchestration_context.repeated_suspended_result
    assert first is not None
    assert second is not None
    assert second.checkpoint_id == first.checkpoint_id
    assert second.idempotency_key == first.idempotency_key
