"""LangGraph wrapper for structured generation orchestration."""

import dataclasses as dc
import importlib
import time
import typing as typ
import uuid

from langgraph.graph import END, START, StateGraph

from episodic.llm import LLMUsage
from episodic.orchestration._types import _log_event
from episodic.orchestration._usage import build_generation_result

if typ.TYPE_CHECKING:
    from langgraph.graph.state import CompiledStateGraph

    from episodic.orchestration import _dto as dto
    from episodic.orchestration import _protocols as protocols
else:
    dto = importlib.import_module("episodic.orchestration._dto")
    protocols = importlib.import_module("episodic.orchestration._protocols")


@dc.dataclass(slots=True)
class GenerationGraphState:
    """Typed graph state for initialize-plan-execute-finish orchestration."""

    request: dto.GenerationOrchestrationRequest | None = None
    planner_result: dto.PlannerResult | None = None
    action_results: tuple[dto.ActionExecutionResult, ...] = ()
    orchestration_result: dto.GenerationOrchestrationResult | None = None
    suspended_result: dto.SuspendedWorkflowResult | None = None


def _usage_to_payload(usage: LLMUsage | None) -> dict[str, int] | None:
    """Return a JSON-compatible LLMUsage payload."""
    if usage is None:
        return None
    return {
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "total_tokens": usage.total_tokens,
    }


def _as_object_payload(payload: object, field_name: str) -> dict[str, object]:
    """Return payload as a string-keyed object."""
    if not isinstance(payload, dict):
        msg = f"checkpoint {field_name} payload must be an object."
        raise TypeError(msg)
    return typ.cast("dict[str, object]", payload)


def _required_int(payload: dict[str, object], field_name: str) -> int:
    """Return an integer field from a checkpoint payload."""
    value = payload[field_name]
    if not isinstance(value, int):
        msg = f"checkpoint {field_name} must be an integer."
        raise TypeError(msg)
    return value


def _required_string(payload: dict[str, object], field_name: str) -> str:
    """Return a string field from a checkpoint payload."""
    value = payload[field_name]
    if not isinstance(value, str):
        msg = f"checkpoint {field_name} must be a string."
        raise TypeError(msg)
    return value


def _usage_from_payload(payload: object) -> LLMUsage:
    """Return LLMUsage from a checkpoint payload."""
    usage_payload = _as_object_payload(payload, "usage")
    return LLMUsage(
        input_tokens=_required_int(usage_payload, "input_tokens"),
        output_tokens=_required_int(usage_payload, "output_tokens"),
        total_tokens=_required_int(usage_payload, "total_tokens"),
    )


def _plan_to_payload(plan: dto.ExecutionPlan) -> dict[str, object]:
    """Return a JSON-compatible execution-plan checkpoint payload."""
    return {
        "plan_version": plan.plan_version,
        "selected_planning_model": plan.selected_planning_model,
        "selected_execution_model": plan.selected_execution_model,
        "steps": [
            {
                "action_id": action.action_id,
                "action_kind": str(action.action_kind),
                "rationale": action.rationale,
                "model_tier": str(action.model_tier),
                "required_inputs": list(action.required_inputs),
            }
            for action in plan.steps
        ],
    }


def _plan_from_payload(payload: object) -> dto.ExecutionPlan:
    """Return an ExecutionPlan from a checkpoint payload."""
    plan_payload = _as_object_payload(payload, "plan")
    steps = plan_payload.get("steps")
    if not isinstance(steps, list):
        msg = "checkpoint plan steps must be a list."
        raise TypeError(msg)
    return dto.ExecutionPlan(
        plan_version=_required_string(plan_payload, "plan_version"),
        selected_planning_model=_required_string(
            plan_payload,
            "selected_planning_model",
        ),
        selected_execution_model=_required_string(
            plan_payload,
            "selected_execution_model",
        ),
        steps=tuple(
            dto.PlannedAction(
                action_id=_required_string(step, "action_id"),
                action_kind=dto.ActionKind(_required_string(step, "action_kind")),
                rationale=_required_string(step, "rationale"),
                model_tier=dto.ModelTier(_required_string(step, "model_tier")),
                required_inputs=tuple(
                    str(item)
                    for item in typ.cast(
                        "list[object]",
                        step["required_inputs"],
                    )
                ),
            )
            for step in typ.cast("list[dict[str, object]]", steps)
        ),
    )


def _planner_result_to_payload(result: dto.PlannerResult) -> dict[str, object]:
    """Return a JSON-compatible planner-result checkpoint payload."""
    return {
        "plan": _plan_to_payload(result.plan),
        "usage": _usage_to_payload(result.usage),
        "model": result.model,
        "provider_response_id": result.provider_response_id,
        "finish_reason": result.finish_reason,
    }


def _planner_result_from_payload(payload: object) -> dto.PlannerResult:
    """Return a PlannerResult from a checkpoint payload."""
    planner_payload = _as_object_payload(payload, "planner_result")
    return dto.PlannerResult(
        plan=_plan_from_payload(planner_payload["plan"]),
        usage=_usage_from_payload(planner_payload["usage"]),
        model=_required_string(planner_payload, "model"),
        provider_response_id=_required_string(planner_payload, "provider_response_id"),
        finish_reason=(
            None
            if planner_payload.get("finish_reason") is None
            else _required_string(planner_payload, "finish_reason")
        ),
    )


def _action_result_to_payload(result: dto.ActionExecutionResult) -> dict[str, object]:
    """Return a JSON-compatible action-result checkpoint payload."""
    return {
        "action_id": result.action_id,
        "action_kind": str(result.action_kind),
        "model_tier": str(result.model_tier),
        "model": result.model,
        "summary": result.summary,
        "usage": _usage_to_payload(result.usage),
    }


def _action_result_from_payload(payload: object) -> dto.ActionExecutionResult:
    """Return an ActionExecutionResult from a checkpoint payload."""
    action_payload = _as_object_payload(payload, "action_result")
    return dto.ActionExecutionResult(
        action_id=_required_string(action_payload, "action_id"),
        action_kind=dto.ActionKind(_required_string(action_payload, "action_kind")),
        model_tier=dto.ModelTier(_required_string(action_payload, "model_tier")),
        model=_required_string(action_payload, "model"),
        summary=_required_string(action_payload, "summary"),
        usage=(
            None
            if action_payload.get("usage") is None
            else _usage_from_payload(action_payload["usage"])
        ),
    )


async def _plan_node(
    state: GenerationGraphState,
    *,
    planner: protocols.PlannerPort,
) -> dict[str, dto.PlannerResult]:
    """Validate state and invoke the planner to produce a PlannerResult."""
    request = state.request
    correlation_id = request.correlation_id if request is not None else None
    _log_event(
        "debug",
        "generation_graph.plan_node.start",
        correlation_id=correlation_id,
    )
    if request is None:
        msg = "missing required state value: request"
        raise ValueError(msg)
    try:
        planner_result = await planner.plan(request)
    except Exception as exc:
        _log_event(
            "error",
            "generation_graph.plan_node.error",
            correlation_id=request.correlation_id,
            error=str(exc),
        )
        raise
    result = {"planner_result": planner_result}
    _log_event(
        "debug",
        "generation_graph.plan_node.finish",
        correlation_id=request.correlation_id,
    )
    return result


async def _execute_node(
    state: GenerationGraphState,
    *,
    tool_executor: protocols.ToolExecutorPort,
) -> dict[str, tuple[dto.ActionExecutionResult, ...]]:
    """Validate state and execute each planned action through the tool executor."""
    request = state.request
    correlation_id = request.correlation_id if request is not None else None
    _log_event(
        "debug",
        "generation_graph.execute_node.start",
        correlation_id=correlation_id,
    )
    if request is None:
        msg = "missing required state value: request"
        raise ValueError(msg)
    planner_result = state.planner_result
    if planner_result is None:
        msg = "missing required state value: planner_result"
        raise ValueError(msg)

    # Keep tool execution ordered so the graph mirrors application-service semantics.
    action_results: list[dto.ActionExecutionResult] = []
    for action in planner_result.plan.steps:
        started_at = time.monotonic()
        action_fields = {
            "correlation_id": request.correlation_id,
            "action_id": action.action_id,
            "action_kind": str(action.action_kind),
            "model_tier": str(action.model_tier),
            "execution_model": planner_result.plan.selected_execution_model,
        }
        try:
            action_result = await tool_executor.execute(action, request)
        except Exception as exc:
            _log_event(
                "error",
                "generation_graph.execute_node.action.error",
                **action_fields,
                elapsed_ms=round((time.monotonic() - started_at) * 1000, 1),
                error=str(exc),
            )
            raise
        action_fields["execution_model"] = action_result.model
        _log_event(
            "debug",
            "generation_graph.execute_node.action.finish",
            **action_fields,
            elapsed_ms=round((time.monotonic() - started_at) * 1000, 1),
        )
        action_results.append(action_result)
    result = {"action_results": tuple(action_results)}
    _log_event(
        "debug",
        "generation_graph.execute_node.finish",
        correlation_id=request.correlation_id,
    )
    return result


async def _suspend_execute_node(
    state: GenerationGraphState,
    *,
    checkpoint_port: protocols.CheckpointPort,
    workflow_type: str = "generation_orchestration",
) -> dict[str, dto.SuspendedWorkflowResult]:
    """Persist a checkpoint before executing the first action."""
    request = state.request
    if request is None:
        msg = "missing required state value: request"
        raise ValueError(msg)
    planner_result = state.planner_result
    if planner_result is None:
        msg = "missing required state value: planner_result"
        raise ValueError(msg)
    if not planner_result.plan.steps:
        msg = "cannot suspend a workflow with no planned steps"
        raise ValueError(msg)

    action = planner_result.plan.steps[0]
    workflow_id = request.correlation_id
    idempotency_key = dto.build_workflow_step_idempotency_key(
        workflow_id=workflow_id,
        workflow_type=workflow_type,
        step_name="execute",
        action_id=action.action_id,
    )
    existing = await checkpoint_port.get_by_idempotency_key(idempotency_key)
    if existing is None:
        existing = await checkpoint_port.save(
            dto.WorkflowCheckpoint(
                checkpoint_id=str(uuid.uuid4()),
                workflow_id=workflow_id,
                workflow_type=workflow_type,
                step_name="execute",
                idempotency_key=idempotency_key,
                payload={
                    "request": {
                        "correlation_id": request.correlation_id,
                        "script_tei_xml": request.script_tei_xml,
                        "template_structure": request.template_structure,
                    },
                    "planner_result": _planner_result_to_payload(planner_result),
                },
            )
        )
    suspended_result = dto.SuspendedWorkflowResult(
        checkpoint_id=existing.checkpoint_id,
        workflow_id=existing.workflow_id,
        step_name=existing.step_name,
        idempotency_key=existing.idempotency_key,
    )
    return {"suspended_result": suspended_result}


async def resume_generation_orchestration(
    *,
    checkpoint_port: protocols.CheckpointPort,
    resume_port: protocols.TaskResumePort,
    command: dto.ResumeWorkflowCommand,
) -> dto.GenerationOrchestrationResult:
    """Resume a suspended generation workflow and return the final result."""
    checkpoint = await checkpoint_port.get(command.checkpoint_id)
    if checkpoint is None:
        msg = f"unknown checkpoint: {command.checkpoint_id}"
        raise ValueError(msg)
    payload = checkpoint.payload
    planner_result = _planner_result_from_payload(payload["planner_result"])
    action_result = await resume_port.resume(command)
    return build_generation_result(planner_result, (action_result,))


def _finish_node(
    state: GenerationGraphState,
) -> dict[str, dto.GenerationOrchestrationResult]:
    """Aggregate planner and action results into a GenerationOrchestrationResult."""
    request = state.request
    correlation_id = request.correlation_id if request is not None else None
    _log_event(
        "debug",
        "generation_graph.finish_node.start",
        correlation_id=correlation_id,
    )
    if request is None:
        msg = "missing required state value: request"
        raise ValueError(msg)
    planner_result = state.planner_result
    if planner_result is None:
        msg = "missing required state value: planner_result"
        raise ValueError(msg)
    try:
        orchestration_result = build_generation_result(
            planner_result,
            state.action_results,
        )
    except Exception as exc:
        _log_event(
            "error",
            "generation_graph.finish_node.error",
            correlation_id=correlation_id,
            error=str(exc),
        )
        raise
    result = {"orchestration_result": orchestration_result}
    _log_event(
        "debug",
        "generation_graph.finish_node.finish",
        correlation_id=correlation_id,
    )
    return result


def build_generation_orchestration_graph(
    *,
    planner: protocols.PlannerPort,
    tool_executor: protocols.ToolExecutorPort,
    checkpoint_port: protocols.CheckpointPort | None = None,
) -> CompiledStateGraph[
    GenerationGraphState,
    None,
    GenerationGraphState,
    GenerationGraphState,
]:
    """Build the minimal in-process generation orchestration graph."""
    graph = StateGraph(GenerationGraphState)

    async def _run_plan_node(
        state: GenerationGraphState,
    ) -> dict[str, dto.PlannerResult]:
        """Async entry point for the plan graph node."""
        return await _plan_node(state, planner=planner)

    async def _run_execute_node(
        state: GenerationGraphState,
    ) -> dict[str, tuple[dto.ActionExecutionResult, ...]]:
        """Async entry point for the execute graph node."""
        return await _execute_node(state, tool_executor=tool_executor)

    graph.add_node("plan", _run_plan_node)
    if checkpoint_port is None:
        graph.add_node("execute", _run_execute_node)
    else:

        async def _run_suspend_execute_node(
            state: GenerationGraphState,
        ) -> dict[str, dto.SuspendedWorkflowResult]:
            """Async entry point for the suspend-before-execute graph node."""
            return await _suspend_execute_node(
                state,
                checkpoint_port=checkpoint_port,
            )

        graph.add_node("execute", _run_suspend_execute_node)
    graph.add_node("finish", _finish_node)
    graph.add_edge(START, "plan")
    graph.add_edge("plan", "execute")
    if checkpoint_port is None:
        graph.add_edge("execute", "finish")
    else:
        graph.add_edge("execute", END)
    graph.add_edge("finish", END)
    return graph.compile()
