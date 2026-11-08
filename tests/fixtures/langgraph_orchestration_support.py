"""Fakes and builders for the structured generation LangGraph seam tests."""

import dataclasses as dc

from episodic.llm import LLMUsage
from episodic.orchestration import (
    ActionExecutionResult,
    ActionKind,
    ExecutionPlan,
    GenerationOrchestrationRequest,
    ModelTier,
    PlannedAction,
    PlannerResult,
    ResumeWorkflowCommand,
)


@dc.dataclass(slots=True)
class FakePlanner:
    """Return one canned planning result."""

    result: PlannerResult

    async def plan(
        self,
        request: GenerationOrchestrationRequest,
    ) -> PlannerResult:
        """Return the canned result after validating the request."""
        assert request.script_tei_xml.startswith("<TEI>"), (
            "expected script_tei_xml to start with '<TEI>', got: "
            f"{request.script_tei_xml!r}"
        )
        return self.result


@dc.dataclass(slots=True)
class FakeToolExecutor:
    """Return one canned execution result."""

    result: ActionExecutionResult
    calls: list[tuple[PlannedAction, GenerationOrchestrationRequest]] = dc.field(
        default_factory=list
    )

    async def execute(
        self,
        action: PlannedAction,
        context: GenerationOrchestrationRequest,
    ) -> ActionExecutionResult:
        """Return the canned result after validating the action and context."""
        assert action.action_kind is ActionKind.GENERATE_SHOW_NOTES, (
            "expected action_kind to be GENERATE_SHOW_NOTES, got: "
            f"{action.action_kind!r}"
        )
        assert context.correlation_id == "corr-graph", (
            "expected correlation_id to be 'corr-graph', got: "
            f"{context.correlation_id!r}"
        )
        self.calls.append((action, context))
        return self.result


@dc.dataclass(slots=True)
class FakeResumePort:
    """Return the externally supplied action result for resume tests."""

    calls: list[ResumeWorkflowCommand] = dc.field(default_factory=list)

    async def resume(
        self,
        command: ResumeWorkflowCommand,
    ) -> ActionExecutionResult:
        """Record and return the command result."""
        self.calls.append(command)
        return command.result


def build_request() -> GenerationOrchestrationRequest:
    """Build a graph request for orchestration tests.

    Returns
    -------
    GenerationOrchestrationRequest
        Request with a fixed correlation ID and a minimal TEI script.
    """
    return GenerationOrchestrationRequest(
        correlation_id="corr-graph",
        script_tei_xml="<TEI><text><body><p>Graph request</p></body></text></TEI>",
    )


def build_planner_result() -> PlannerResult:
    """Build a planner result with one show-notes step.

    Returns
    -------
    PlannerResult
        Planner output with a single planned action and token usage.
    """
    return PlannerResult(
        plan=ExecutionPlan(
            plan_version="1.0",
            selected_planning_model="gpt-4.1",
            selected_execution_model="gpt-4o-mini",
            steps=(
                PlannedAction(
                    action_id="action-1",
                    action_kind=ActionKind.GENERATE_SHOW_NOTES,
                    rationale="Need show notes.",
                    model_tier=ModelTier.EXECUTION,
                    required_inputs=("script_tei_xml",),
                ),
            ),
        ),
        usage=LLMUsage(input_tokens=15, output_tokens=9, total_tokens=24),
        model="gpt-4.1",
        provider_response_id="planner-1",
        finish_reason="stop",
    )


def build_multi_step_planner_result() -> PlannerResult:
    """Return a planner result that exposes unsupported multi-step resume."""
    result = build_planner_result()
    first_step = result.plan.steps[0]
    second_step = PlannedAction(
        action_id="action-2",
        action_kind=ActionKind.GENERATE_SHOW_NOTES,
        rationale="Need a second pass.",
        model_tier=ModelTier.EXECUTION,
        required_inputs=("script_tei_xml",),
    )
    return PlannerResult(
        plan=ExecutionPlan(
            plan_version=result.plan.plan_version,
            selected_planning_model=result.plan.selected_planning_model,
            selected_execution_model=result.plan.selected_execution_model,
            steps=(first_step, second_step),
        ),
        usage=result.usage,
        model=result.model,
        provider_response_id=result.provider_response_id,
        finish_reason=result.finish_reason,
    )


def build_action_result() -> ActionExecutionResult:
    """Build a show-notes action result with token usage.

    Returns
    -------
    ActionExecutionResult
        Successful execution result for the ``action-1`` step.
    """
    return ActionExecutionResult(
        action_id="action-1",
        action_kind=ActionKind.GENERATE_SHOW_NOTES,
        model_tier=ModelTier.EXECUTION,
        model="gpt-4o-mini",
        summary="Generated show notes.",
        usage=LLMUsage(input_tokens=10, output_tokens=4, total_tokens=14),
    )
