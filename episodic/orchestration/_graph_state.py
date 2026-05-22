"""LangGraph state container for generation orchestration."""

import dataclasses as dc
import importlib
import typing as typ

if typ.TYPE_CHECKING:
    from episodic.orchestration import _dto as dto
else:
    dto = importlib.import_module("episodic.orchestration._dto")


@dc.dataclass(slots=True)
class GenerationGraphState:
    """Typed graph state for initialize-plan-execute-finish orchestration."""

    request: dto.GenerationOrchestrationRequest | None = None
    planner_result: dto.PlannerResult | None = None
    action_results: tuple[dto.ActionExecutionResult, ...] = ()
    orchestration_result: dto.GenerationOrchestrationResult | None = None
    suspended_result: dto.SuspendedWorkflowResult | None = None
