"""Structured planning orchestrator implementation."""

from __future__ import annotations

import dataclasses as dc
import time
import typing as typ

from episodic.llm import LLMError

from ._types import (
    PlanningResponseFormatError,
    ToolExecutionError,
    UnsupportedActionError,
    _log_event,
)
from ._usage import build_generation_result

if typ.TYPE_CHECKING:
    import collections.abc as cabc

    from ._dto import (
        ActionExecutionResult,
        ExecutionPlan,
        GenerationOrchestrationRequest,
        GenerationOrchestrationResult,
        PlannedAction,
        PlannerResult,
    )
    from ._protocols import PlannerPort, ToolExecutorPort


@dc.dataclass(slots=True)
class StructuredPlanningOrchestrator:
    """Plan one orchestration run, then execute each planned action in order."""

    planner: PlannerPort
    tool_executor: ToolExecutorPort

    def _execute_single_action(
        self,
        action: PlannedAction,
        request: GenerationOrchestrationRequest,
        plan: ExecutionPlan,
    ) -> cabc.Awaitable[ActionExecutionResult]:
        """Execute one planned action with the standard action log envelope."""

        async def execute() -> ActionExecutionResult:
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
            return result

        return execute()

    async def execute_plan(
        self,
        *,
        request: GenerationOrchestrationRequest,
        plan: ExecutionPlan,
    ) -> tuple[ActionExecutionResult, ...]:
        """Execute each plan step sequentially through the tool-execution port."""
        results: list[ActionExecutionResult] = []
        for action in plan.steps:
            results.append(  # noqa: PERF401 - keep execution sequential and explicit.
                await self._execute_single_action(action, request, plan)
            )
        return tuple(results)

    def _log_orchestrate_error(  # noqa: PLR6301 - keep orchestration log helper on the instance.
        self,
        exc: Exception,
        *,
        correlation_id: str,
        stage: str,
    ) -> None:
        """Emit the standard orchestration-stage error event."""
        _log_event(
            "error",
            "structured_planning_orchestrator.orchestrate.error",
            correlation_id=correlation_id,
            stage=stage,
            error_type=type(exc).__name__,
            error=str(exc),
        )

    def _run_planner(
        self,
        request: GenerationOrchestrationRequest,
    ) -> cabc.Awaitable[PlannerResult]:
        """Run the planner with the orchestration-level error log envelope."""

        async def run() -> PlannerResult:
            try:
                return await self.planner.plan(request)
            except (LLMError, PlanningResponseFormatError) as exc:
                self._log_orchestrate_error(
                    exc,
                    correlation_id=request.correlation_id,
                    stage="plan",
                )
                raise

        return run()

    def _run_execute_plan(
        self,
        request: GenerationOrchestrationRequest,
        plan: ExecutionPlan,
    ) -> cabc.Awaitable[tuple[ActionExecutionResult, ...]]:
        """Run tool execution with the orchestration-level error log envelope."""

        async def run() -> tuple[ActionExecutionResult, ...]:
            try:
                return await self.execute_plan(
                    request=request,
                    plan=plan,
                )
            except (LLMError, ToolExecutionError, UnsupportedActionError) as exc:
                self._log_orchestrate_error(
                    exc,
                    correlation_id=request.correlation_id,
                    stage="execute_plan",
                )
                raise

        return run()

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
        planner_result = await self._run_planner(request)
        action_results = await self._run_execute_plan(request, planner_result.plan)
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
