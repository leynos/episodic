"""Structured planning and tool execution for content generation."""

import dataclasses as dc
import json

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
from ._guest_bios_executor import GuestBiosToolExecutor
from ._planning_orchestrator import StructuredPlanningOrchestrator
from ._protocols import PlannerPort, ToolExecutorPort
from ._routing_executor import RoutingToolExecutor
from ._show_notes_executor import ShowNotesToolExecutor
from ._types import (
    ActionKind,
    GuestBiosFormatError,
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
    "GuestBiosFormatError",
    "GuestBiosToolExecutor",
    "ModelTier",
    "PlannedAction",
    "PlannerPort",
    "PlannerResult",
    "PlanningResponseFormatError",
    "ResumeWorkflowCommand",
    "RoutingToolExecutor",
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
    def _coerce_enabled_action_kind(
        value: object,
        *,
        enabled_action_kinds: tuple[ActionKind, ...],
    ) -> ActionKind:
        """Return a planner action kind only when the config enables it."""
        action_kind = _coerce_action_kind(value)
        if action_kind not in enabled_action_kinds:
            expected = ", ".join(action.value for action in enabled_action_kinds)
            msg = f"action_kind must be one of enabled actions: {expected}."
            raise PlanningResponseFormatError(msg)
        return action_kind

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
        enabled_action_kinds = _coerce_action_kinds(config.enabled_action_kinds)
        steps = tuple(
            PlannedAction(
                action_id=_require_non_empty_string(
                    step_payload.get("action_id"),
                    "action_id",
                ),
                action_kind=StructuredGenerationPlanner._coerce_enabled_action_kind(
                    step_payload.get("action_kind"),
                    enabled_action_kinds=enabled_action_kinds,
                ),
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

    def _decode_planner_json(
        self,
        response_text: str,
        *,
        correlation_id: str,
    ) -> dict[str, object]:
        """Decode planner JSON text or raise a deterministic format error."""
        try:
            decoded: dict[str, object] = json.loads(response_text)
        except json.JSONDecodeError as exc:
            msg = "Planner response is not valid JSON."
            _log_event(
                "error",
                "structured_generation_planner.plan.invalid_json",
                correlation_id=correlation_id,
                planning_model=self.config.planning_model,
            )
            raise PlanningResponseFormatError(msg) from exc
        return decoded

    def _parse_and_validate_plan(
        self,
        decoded: object,
        *,
        correlation_id: str,
    ) -> ExecutionPlan:
        """Validate decoded planner payload and return an execution plan."""
        try:
            payload = _require_object(decoded, "planner response")
            plan = self._parse_plan(payload, config=self.config)
        except PlanningResponseFormatError:
            _log_event(
                "error",
                "structured_generation_planner.plan.invalid_plan",
                correlation_id=correlation_id,
                planning_model=self.config.planning_model,
            )
            raise
        return plan

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
        decoded = self._decode_planner_json(
            response.text,
            correlation_id=request.correlation_id,
        )
        plan = self._parse_and_validate_plan(
            decoded,
            correlation_id=request.correlation_id,
        )
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
