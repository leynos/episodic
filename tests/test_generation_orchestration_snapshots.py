"""Syrupy regression snapshots for typed generation artefacts."""

from __future__ import annotations

import dataclasses as dc

from syrupy.assertion import SnapshotAssertion

from episodic.llm import LLMProviderOperation, LLMRequest, LLMResponse, LLMUsage
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
        planning_model="snap-plan-model",
        execution_model="snap-exec-model",
        planning_provider_operation=LLMProviderOperation.CHAT_COMPLETIONS,
        execution_provider_operation=LLMProviderOperation.CHAT_COMPLETIONS,
        enabled_action_kinds=("generate_show_notes",),
    )
    planner = StructuredGenerationPlanner(llm=_UnusedLLMPort(), config=cfg)
    request = GenerationOrchestrationRequest(
        correlation_id="snap-001",
        script_tei_xml="<TEI><text><body><p>Snapshot teaser</p></body></text></TEI>",
    )
    assert planner.build_prompt(request) == snapshot


def test_execution_plan_serialisation_snapshot(snapshot: SnapshotAssertion) -> None:
    planned = PlannedAction(
        action_id="snap-act",
        action_kind=ActionKind.GENERATE_SHOW_NOTES,
        rationale="Snapshot rationale string.",
        model_tier=ModelTier.EXECUTION,
        required_inputs=("script_tei_xml", "template_structure"),
    )
    plan = ExecutionPlan(
        plan_version="snap-plan-version",
        selected_planning_model="snap-planning",
        selected_execution_model="snap-execution",
        steps=(planned,),
    )
    serialised = dc.asdict(plan)
    assert serialised == snapshot


def test_generation_orchestration_result_snapshot(
    snapshot: SnapshotAssertion,
) -> None:
    planned = PlannedAction(
        action_id="snap-act",
        action_kind=ActionKind.GENERATE_SHOW_NOTES,
        rationale="Completed snap step.",
        model_tier=ModelTier.EXECUTION,
        required_inputs=("script_tei_xml",),
    )
    plan = ExecutionPlan(
        plan_version="snap-plan-version",
        selected_planning_model="snap-planning",
        selected_execution_model="snap-execution",
        steps=(planned,),
    )
    action_done = ActionExecutionResult(
        action_id="snap-act",
        action_kind=ActionKind.GENERATE_SHOW_NOTES,
        model_tier=ModelTier.EXECUTION,
        model="snap-worker-model",
        summary="Executed snapshot enrichment.",
        usage=LLMUsage(input_tokens=6, output_tokens=4, total_tokens=10),
    )
    result = GenerationOrchestrationResult(
        plan=plan,
        action_results=(action_done,),
        planner_usage=LLMUsage(input_tokens=40, output_tokens=20, total_tokens=60),
        total_usage=LLMUsage(input_tokens=46, output_tokens=24, total_tokens=70),
    )
    serialised = dc.asdict(result)
    assert serialised == snapshot
