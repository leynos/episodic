"""Syrupy regression snapshots for typed generation artefacts."""

import dataclasses

from syrupy.assertion import SnapshotAssertion

from episodic.llm import LLMRequest, LLMResponse, LLMUsage
from episodic.orchestration import (
    ActionExecutionResult,
    ActionKind,
    ExecutionPlan,
    GenerationOrchestrationConfig,
    GenerationOrchestrationRequest,
    GenerationOrchestrationResult,
    ModelTier,
    PlannedAction,
    StructuredGenerationPlanner,
)


class _UnusedLLMPort:
    """LLM shim only required for constructing `StructuredGenerationPlanner`."""

    async def generate(self, request: LLMRequest) -> LLMResponse:
        """Unreachable for prompt-only assertions."""
        msg = (
            "StructuredGenerationPlanner.build_prompt snapshot harness must "
            f"never await generate ({request=!r})."
        )
        raise RuntimeError(msg)


def test_build_prompt_snapshot(snapshot: SnapshotAssertion) -> None:
    cfg = GenerationOrchestrationConfig(
        planning_model="gpt-4.1",
        execution_model="gpt-4o-mini",
    )
    planner = StructuredGenerationPlanner(llm=_UnusedLLMPort(), config=cfg)
    request = GenerationOrchestrationRequest(
        correlation_id="snap-001",
        script_tei_xml="<TEI><text>test</text></TEI>",
        template_structure=None,
    )
    assert planner.build_prompt(request) == snapshot


def test_execution_plan_serialisation_snapshot(snapshot: SnapshotAssertion) -> None:
    planned = PlannedAction(
        action_id="a1",
        action_kind=ActionKind.GENERATE_SHOW_NOTES,
        rationale="test",
        model_tier=ModelTier.EXECUTION,
    )
    plan = ExecutionPlan(
        plan_version="1",
        selected_planning_model="gpt-4.1",
        selected_execution_model="gpt-4o-mini",
        steps=(planned,),
    )
    serialised = dataclasses.asdict(plan)
    assert serialised == snapshot


def test_generation_orchestration_result_snapshot(
    snapshot: SnapshotAssertion,
) -> None:
    planned = PlannedAction(
        action_id="a1",
        action_kind=ActionKind.GENERATE_SHOW_NOTES,
        rationale="test",
        model_tier=ModelTier.EXECUTION,
    )
    plan = ExecutionPlan(
        plan_version="1",
        selected_planning_model="gpt-4.1",
        selected_execution_model="gpt-4o-mini",
        steps=(planned,),
    )
    action_done = ActionExecutionResult(
        action_id="a1",
        action_kind=ActionKind.GENERATE_SHOW_NOTES,
        model_tier=ModelTier.EXECUTION,
        model="gpt-4o-mini",
        summary="test",
        usage=LLMUsage(input_tokens=10, output_tokens=20, total_tokens=30),
    )
    result = GenerationOrchestrationResult(
        plan=plan,
        action_results=(action_done,),
        planner_usage=LLMUsage(input_tokens=1, output_tokens=2, total_tokens=3),
        total_usage=LLMUsage(input_tokens=11, output_tokens=22, total_tokens=33),
    )
    serialised = dataclasses.asdict(result)
    assert serialised == snapshot
