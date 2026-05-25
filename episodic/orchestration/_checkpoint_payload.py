"""Checkpoint payload serialization helpers for generation orchestration.

This module owns the JSON-compatible payload shape persisted through
`CheckpointPort` when `langgraph.py` takes the suspend-before-execute path.
`_checkpoint_resume.py` uses these helpers to store `PlannerResult` values in a
workflow checkpoint and to rebuild them when
`resume_generation_orchestration(...)` receives an external task result.

The conversion helpers keep checkpoint payload validation close to the DTOs
they reconstruct. `_planner_result_to_payload(...)` and
`_planner_result_from_payload(...)` are the main suspend/resume boundary; the
plan, action-result, and usage helpers support property tests and snapshot
coverage for that persisted contract.
"""

import enum
import typing as typ

from episodic.llm import LLMUsage

if typ.TYPE_CHECKING:
    import importlib

    from episodic.orchestration import _dto as dto
else:
    import importlib

    dto = importlib.import_module("episodic.orchestration._dto")


def _usage_to_payload(usage: LLMUsage | None) -> dict[str, int] | None:
    """Return a JSON-compatible LLMUsage payload."""
    if usage is None:
        return None
    return {
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "total_tokens": usage.total_tokens,
    }


def _as_object_payload(payload: object, context: str) -> dict[str, object]:
    """Return payload as a string-keyed object."""
    if not isinstance(payload, dict):
        msg = f"checkpoint {context} payload must be an object."
        raise TypeError(msg)
    return typ.cast("dict[str, object]", payload)


def _require_field[FieldT](
    payload: dict[str, object],
    field_name: str,
    expected_type: type[FieldT],
    *,
    context: str,
) -> FieldT:
    """Return a required typed checkpoint payload field."""
    try:
        value = payload[field_name]
    except KeyError as exc:
        msg = f"checkpoint {context} missing required field: {field_name}"
        raise TypeError(msg) from exc
    if not isinstance(value, expected_type):
        msg = (
            f"checkpoint {context} field {field_name} must be a "
            f"{expected_type.__name__}."
        )
        raise TypeError(msg)
    return value


def _required_int(
    payload: dict[str, object],
    field_name: str,
    *,
    context: str,
) -> int:
    """Return an integer field from a checkpoint payload."""
    return _require_field(payload, field_name, int, context=context)


def _required_string(
    payload: dict[str, object],
    field_name: str,
    *,
    context: str,
) -> str:
    """Return a string field from a checkpoint payload."""
    return _require_field(payload, field_name, str, context=context)


def _required_enum[EnumT: enum.Enum](
    payload: dict[str, object],
    field_name: str,
    enum_type: type[EnumT],
    *,
    context: str,
) -> EnumT:
    """Return an enum field from a checkpoint payload."""
    value = _required_string(payload, field_name, context=context)
    try:
        return enum_type(value)
    except ValueError as exc:
        msg = (
            f"checkpoint {context} field {field_name} must be a valid "
            f"{enum_type.__name__}."
        )
        raise TypeError(msg) from exc


def _required_string_list(
    payload: dict[str, object],
    field_name: str,
    *,
    context: str,
) -> tuple[str, ...]:
    """Return a list-of-strings field from a checkpoint payload."""
    items = _require_field(payload, field_name, list, context=context)
    if not all(isinstance(item, str) for item in items):
        msg = f"checkpoint {context} field {field_name} must be a list of strings."
        raise TypeError(msg)
    return tuple(items)


def _usage_from_payload(payload: object) -> LLMUsage:
    """Return LLMUsage from a checkpoint payload."""
    usage_payload = _as_object_payload(payload, "usage")
    return LLMUsage(
        input_tokens=_required_int(usage_payload, "input_tokens", context="usage"),
        output_tokens=_required_int(usage_payload, "output_tokens", context="usage"),
        total_tokens=_required_int(usage_payload, "total_tokens", context="usage"),
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


def _planned_action_from_payload(payload: object) -> dto.PlannedAction:
    """Return one PlannedAction from a checkpoint plan-step payload."""
    step = _as_object_payload(payload, "plan step")
    return dto.PlannedAction(
        action_id=_required_string(step, "action_id", context="plan step"),
        action_kind=_required_enum(
            step,
            "action_kind",
            dto.ActionKind,
            context="plan step",
        ),
        rationale=_required_string(step, "rationale", context="plan step"),
        model_tier=_required_enum(
            step,
            "model_tier",
            dto.ModelTier,
            context="plan step",
        ),
        required_inputs=_required_string_list(
            step,
            "required_inputs",
            context="plan step",
        ),
    )


def _plan_from_payload(payload: object) -> dto.ExecutionPlan:
    """Return an ExecutionPlan from a checkpoint payload."""
    plan_payload = _as_object_payload(payload, "plan")
    steps = plan_payload.get("steps")
    if not isinstance(steps, list):
        msg = "checkpoint plan steps must be a list."
        raise TypeError(msg)
    return dto.ExecutionPlan(
        plan_version=_required_string(
            plan_payload,
            "plan_version",
            context="plan",
        ),
        selected_planning_model=_required_string(
            plan_payload,
            "selected_planning_model",
            context="plan",
        ),
        selected_execution_model=_required_string(
            plan_payload,
            "selected_execution_model",
            context="plan",
        ),
        steps=tuple(_planned_action_from_payload(step) for step in steps),
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
    try:
        plan_payload = planner_payload["plan"]
    except KeyError as exc:
        msg = "checkpoint planner_result missing required field: plan"
        raise TypeError(msg) from exc
    return dto.PlannerResult(
        plan=_plan_from_payload(plan_payload),
        usage=(
            None
            if planner_payload.get("usage") is None
            else _usage_from_payload(planner_payload["usage"])
        ),
        model=_required_string(planner_payload, "model", context="planner_result"),
        provider_response_id=_required_string(
            planner_payload,
            "provider_response_id",
            context="planner_result",
        ),
        finish_reason=(
            None
            if planner_payload.get("finish_reason") is None
            else _required_string(
                planner_payload,
                "finish_reason",
                context="planner_result",
            )
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
        action_id=_required_string(
            action_payload, "action_id", context="action_result"
        ),
        action_kind=_required_enum(
            action_payload,
            "action_kind",
            dto.ActionKind,
            context="action_result",
        ),
        model_tier=_required_enum(
            action_payload,
            "model_tier",
            dto.ModelTier,
            context="action_result",
        ),
        model=_required_string(action_payload, "model", context="action_result"),
        summary=_required_string(action_payload, "summary", context="action_result"),
        usage=(
            None
            if action_payload.get("usage") is None
            else _usage_from_payload(action_payload["usage"])
        ),
    )
