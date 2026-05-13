"""Structured planning and tool execution for content generation."""

import dataclasses as dc
import json
import time

from episodic.llm import (
    LLMError,
    LLMPort,
    LLMRequest,
)

from ._dto import (
    ActionExecutionResult,
    ExecutionPlan,
    GenerationOrchestrationConfig,
    GenerationOrchestrationRequest,
    GenerationOrchestrationResult,
    PlannedAction,
    PlannerResult,
    ResumeWorkflowCommand,
    SuspendedWorkflowResult,
    WorkflowCheckpoint,
    WorkflowStepIdentity,
    _coerce_action_kind,
    _coerce_action_kinds,
    _coerce_model_tier,
    _require_non_empty_string,
    _require_object,
    _require_optional_string_list,
    _require_plan_step_list,
    build_workflow_step_idempotency_key,
)
from ._protocols import PlannerPort, ToolExecutorPort
from ._show_notes_executor import ShowNotesToolExecutor
from ._types import (
    ActionKind,
    ModelTier,
    PlanningResponseFormatError,
    ShowNotesFormatError,
    ToolExecutionError,
    UnsupportedActionError,
    _log_event,
)
from ._usage import build_generation_result

__all__ = [
    "ActionExecutionResult",
    "ActionKind",
    "ExecutionPlan",
    "GenerationOrchestrationConfig",
    "GenerationOrchestrationRequest",
    "GenerationOrchestrationResult",
    "ModelTier",
    "PlannedAction",
    "PlannerPort",
    "PlannerResult",
    "PlanningResponseFormatError",
    "ResumeWorkflowCommand",
    "ShowNotesFormatError",
    "ShowNotesToolExecutor",
    "StructuredGenerationPlanner",
    "StructuredPlanningOrchestrator",
    "SuspendedWorkflowResult",
    "ToolExecutionError",
    "ToolExecutorPort",
    "UnsupportedActionError",
    "WorkflowCheckpoint",
    "WorkflowStepIdentity",
    "build_generation_result",
    "build_workflow_step_idempotency_key",
]


@dc.dataclass(slots=True)
class StructuredGenerationPlanner:
    """Generate and validate one strict execution plan via `LLMPort`."""

    llm: LLMPort
    config: GenerationOrchestrationConfig

    @staticmethod
    def _parse_plan(
        payload: dict[str, object],
        *,
        config: GenerationOrchestrationConfig,
    ) -> ExecutionPlan:
        """Parse raw LLM JSON text into a validated ExecutionPlan."""
        plan_version = _require_non_empty_string(
            payload.get("plan_version"),
            "plan_version",
        )
        step_payloads = _require_plan_step_list(payload.get("steps"))
        steps = tuple(
            PlannedAction(
                action_id=_require_non_empty_string(
                    step_payload.get("action_id"),
                    "action_id",
                ),
                action_kind=_coerce_action_kind(step_payload.get("action_kind")),
                rationale=_require_non_empty_string(
                    step_payload.get("rationale"),
                    "rationale",
                ),
                model_tier=_coerce_model_tier(step_payload.get("model_tier")),
                required_inputs=_require_optional_string_list(
                    step_payload.get("required_inputs"),
                    "required_inputs",
                ),
            )
            for step_payload in step_payloads
        )
        return ExecutionPlan(
            plan_version=plan_version,
            selected_planning_model=config.planning_model,
            selected_execution_model=config.execution_model,
            steps=steps,
        )

    def build_prompt(self, request: GenerationOrchestrationRequest) -> str:
        """Build the planner prompt payload."""
        enabled_action_kind_values = [
            action_kind.value
            for action_kind in _coerce_action_kinds(self.config.enabled_action_kinds)
        ]
        prompt_payload: dict[str, object] = {
            "task": (
                "Review the canonical TEI script and decide which enabled "
                "generation-enrichment actions should run."
            ),
            "response_schema": {
                "plan_version": "string",
                "steps": [
                    {
                        "action_id": "string",
                        "action_kind": enabled_action_kind_values,
                        "rationale": "string",
                        "model_tier": [
                            ModelTier.PLANNING.value,
                            ModelTier.EXECUTION.value,
                        ],
                        "required_inputs": ["string"],
                    }
                ],
            },
            "enabled_action_kinds": enabled_action_kind_values,
            "correlation_id": request.correlation_id,
            "script_tei_xml": request.script_tei_xml,
        }
        if request.template_structure is not None:
            prompt_payload["template_structure"] = request.template_structure
        try:
            rendered_payload = json.dumps(
                prompt_payload,
                indent=2,
                ensure_ascii=True,
            )
        except TypeError as exc:
            msg = "template_structure must be JSON-serializable."
            raise ValueError(msg) from exc
        return f"Return JSON only.\n{rendered_payload}"

    async def plan(self, request: GenerationOrchestrationRequest) -> PlannerResult:
        """Call the LLM and parse the strict planner response."""
        _log_event(
            "debug",
            "structured_generation_planner.plan.start",
            correlation_id=request.correlation_id,
            planning_model=self.config.planning_model,
        )
        llm_request = LLMRequest(
            model=self.config.planning_model,
            prompt=self.build_prompt(request),
            system_prompt=self.config.planner_system_prompt,
            provider_operation=self.config.planning_provider_operation,
            token_budget=self.config.planning_token_budget,
        )
        try:
            response = await self.llm.generate(llm_request)
        except LLMError:
            # All LLMError subtypes are logged the same way and re-raised as-is.
            _log_event(
                "error",
                "structured_generation_planner.plan.error",
                correlation_id=request.correlation_id,
                planning_model=self.config.planning_model,
            )
            raise
        try:
            decoded = json.loads(response.text)
        except json.JSONDecodeError as exc:
            msg = "Planner response is not valid JSON."
            _log_event(
                "error",
                "structured_generation_planner.plan.invalid_json",
                correlation_id=request.correlation_id,
                planning_model=self.config.planning_model,
            )
            raise PlanningResponseFormatError(msg) from exc
        try:
            payload = _require_object(decoded, "planner response")
            plan = self._parse_plan(payload, config=self.config)
        except PlanningResponseFormatError:
            _log_event(
                "error",
                "structured_generation_planner.plan.invalid_plan",
                correlation_id=request.correlation_id,
                planning_model=self.config.planning_model,
            )
            raise
        _log_event(
            "info",
            "structured_generation_planner.plan.success",
            correlation_id=request.correlation_id,
            planning_model=self.config.planning_model,
            step_count=len(plan.steps),
        )
        return PlannerResult(
            plan=plan,
            usage=response.usage,
            model=response.model,
            provider_response_id=response.provider_response_id,
            finish_reason=response.finish_reason,
        )


@dc.dataclass(slots=True)
class StructuredPlanningOrchestrator:
    """Plan one orchestration run, then execute each planned action in order."""

    planner: PlannerPort
    tool_executor: ToolExecutorPort

    async def execute_plan(
        self,
        *,
        request: GenerationOrchestrationRequest,
        plan: ExecutionPlan,
    ) -> tuple[ActionExecutionResult, ...]:
        """Execute each plan step sequentially through the tool-execution port."""
        results: list[ActionExecutionResult] = []
        for action in plan.steps:
            _log_event(
                "debug",
                "structured_planning_orchestrator.execute_plan.action.start",
                correlation_id=request.correlation_id,
                action_id=action.action_id,
                action_kind=str(action.action_kind),
                execution_model=plan.selected_execution_model,
            )
            t0 = time.monotonic()
            try:
                result = await self.tool_executor.execute(action, request)
            except (LLMError, ToolExecutionError, UnsupportedActionError) as exc:
                _log_event(
                    "error",
                    "structured_planning_orchestrator.execute_plan.action.error",
                    correlation_id=request.correlation_id,
                    action_id=action.action_id,
                    action_kind=str(action.action_kind),
                    execution_model=plan.selected_execution_model,
                    elapsed_ms=round((time.monotonic() - t0) * 1000, 1),
                    error_type=type(exc).__name__,
                    error=str(exc),
                )
                raise
            _log_event(
                "debug",
                "structured_planning_orchestrator.execute_plan.action.complete",
                correlation_id=request.correlation_id,
                action_id=action.action_id,
                action_kind=str(action.action_kind),
                execution_model=plan.selected_execution_model,
                elapsed_ms=round((time.monotonic() - t0) * 1000, 1),
            )
            results.append(result)
        return tuple(results)

    async def orchestrate(
        self,
        request: GenerationOrchestrationRequest,
    ) -> GenerationOrchestrationResult:
        """Plan and execute one structured generation request."""
        _log_event(
            "info",
            "structured_planning_orchestrator.orchestrate.start",
            correlation_id=request.correlation_id,
        )
        try:
            planner_result = await self.planner.plan(request)
        except (LLMError, PlanningResponseFormatError) as exc:
            _log_event(
                "error",
                "structured_planning_orchestrator.orchestrate.error",
                correlation_id=request.correlation_id,
                stage="plan",
                error_type=type(exc).__name__,
                error=str(exc),
            )
            raise
        try:
            action_results = await self.execute_plan(
                request=request,
                plan=planner_result.plan,
            )
        except (LLMError, ToolExecutionError, UnsupportedActionError) as exc:
            _log_event(
                "error",
                "structured_planning_orchestrator.orchestrate.error",
                correlation_id=request.correlation_id,
                stage="execute_plan",
                error_type=type(exc).__name__,
                error=str(exc),
            )
            raise
        result = build_generation_result(planner_result, action_results)
        _log_event(
            "info",
            "structured_planning_orchestrator.orchestrate.complete",
            correlation_id=request.correlation_id,
            execution_model=planner_result.plan.selected_execution_model,
            input_tokens=result.total_usage.input_tokens,
            output_tokens=result.total_usage.output_tokens,
            total_tokens=result.total_usage.total_tokens,
        )
        return result
