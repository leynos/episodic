"""Checkpoint suspend and resume logic for generation orchestration.

This module contains the checkpoint side of the LangGraph orchestration path.
`langgraph.py` calls `_suspend_execute_node(...)` when a `CheckpointPort` is
provided, so the graph persists the planned execution step and returns a
`SuspendedWorkflowResult` instead of running tools inline.

`resume_generation_orchestration(...)` is the public API for completing that
paused workflow. It reloads the checkpoint payload, rebuilds the planner result
with `_checkpoint_payload` helpers, obtains the external action result from a
`TaskResumePort`, aggregates the final `GenerationOrchestrationResult`, and
marks the checkpoint resumed.
"""

import typing as typ
import uuid

from episodic.orchestration._checkpoint_payload import (
    _planner_result_from_payload,
    _planner_result_to_payload,
)
from episodic.orchestration._types import _log_event
from episodic.orchestration._usage import build_generation_result

if typ.TYPE_CHECKING:
    import importlib

    from episodic.orchestration import _dto as dto
    from episodic.orchestration import _protocols as protocols
    from episodic.orchestration._graph_state import GenerationGraphState
else:
    import importlib

    dto = importlib.import_module("episodic.orchestration._dto")
    protocols = importlib.import_module("episodic.orchestration._protocols")


def _build_execute_step_identity(
    *,
    request: dto.GenerationOrchestrationRequest,
    action: dto.PlannedAction,
    workflow_type: str,
) -> dto.WorkflowStepIdentity:
    """Return the idempotency identity for the execute workflow step."""
    return dto.WorkflowStepIdentity(
        workflow_id=request.correlation_id,
        workflow_type=workflow_type,
        step_name="execute",
        action_id=action.action_id,
    )


def _build_checkpoint_payload(
    *,
    request: dto.GenerationOrchestrationRequest,
    planner_result: dto.PlannerResult,
) -> dict[str, object]:
    """Return the persisted suspend payload for generation resume."""
    return {
        "request": {
            "correlation_id": request.correlation_id,
        },
        "planner_result": _planner_result_to_payload(planner_result),
    }


def _validate_suspend_preconditions(
    state: GenerationGraphState,
) -> tuple[
    dto.GenerationOrchestrationRequest,
    dto.PlannerResult,
    dto.PlannedAction,
]:
    """Validate and extract required state fields for a suspend checkpoint."""
    request = state.request
    if request is None:
        msg = "missing required state value: request"
        raise ValueError(msg)
    planner_result = state.planner_result
    if planner_result is None:
        msg = "missing required state value: planner_result"
        raise ValueError(msg)
    if len(planner_result.plan.steps) != 1:
        msg = "cannot suspend a workflow with no planned steps"
        if planner_result.plan.steps:
            msg = (
                "suspend_generation_orchestration currently supports exactly "
                "one planned step per suspended checkpoint."
            )
        raise ValueError(msg)
    return request, planner_result, planner_result.plan.steps[0]


async def _suspend_execute_node(
    state: GenerationGraphState,
    *,
    checkpoint_port: protocols.CheckpointPort,
    workflow_type: str = "generation_orchestration",
) -> dict[str, dto.SuspendedWorkflowResult]:
    """Persist or reuse a checkpoint before executing the first action.

    The suspend path deliberately performs no pre-save lookup. It always asks
    the checkpoint port to ``save_or_reuse`` a fresh checkpoint and derives
    reuse from the returned checkpoint id. The database-backed port enforces
    the idempotency boundary with the unique ``idempotency_key`` constraint, so
    concurrent invocations for the same workflow step converge on one
    checkpoint without a time-of-check/time-of-use window.

    The returned ``SuspendedWorkflowResult`` is valid whether this invocation
    created the checkpoint or reused a checkpoint created by a concurrent
    caller.
    """
    request, planner_result, action = _validate_suspend_preconditions(state)
    identity = _build_execute_step_identity(
        request=request,
        action=action,
        workflow_type=workflow_type,
    )
    idempotency_key = dto.build_workflow_step_idempotency_key(
        identity,
    )
    _log_event(
        "debug",
        "generation_graph.suspend_execute_node.start",
        correlation_id=request.correlation_id,
        workflow_id=identity.workflow_id,
        workflow_type=identity.workflow_type,
        step_name=identity.step_name,
        action_id=identity.action_id,
        idempotency_key=idempotency_key,
    )
    fresh_id = str(uuid.uuid4())
    existing = await checkpoint_port.save_or_reuse(
        dto.WorkflowCheckpoint(
            checkpoint_id=fresh_id,
            workflow_id=identity.workflow_id,
            workflow_type=identity.workflow_type,
            step_name=identity.step_name,
            idempotency_key=idempotency_key,
            payload=_build_checkpoint_payload(
                request=request,
                planner_result=planner_result,
            ),
        )
    )
    reused_checkpoint = existing.checkpoint_id != fresh_id
    _log_event(
        "debug",
        "generation_graph.suspend_execute_node.finish",
        correlation_id=request.correlation_id,
        checkpoint_id=existing.checkpoint_id,
        idempotency_key=existing.idempotency_key,
        reused_checkpoint=reused_checkpoint,
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
    """Resume a suspended generation workflow and return the final result.

    `resume_generation_orchestration` currently assumes one suspended action
    per checkpoint: `resume_port.resume(command)` returns one action result, and
    `build_generation_result(planner_result, (action_result,))` finalises that
    single result. Any future model that allows one checkpoint to cover
    multiple `planner_result.plan.steps` entries must update this code path.

    The resume action executes before the checkpoint is marked ``resumed``. If
    the action completes and `checkpoint_port.mark_resumed` fails or the caller
    rolls back the unit of work, the checkpoint remains ``suspended``. That
    partial failure is non-destructive, but retry safety then depends on the
    concrete `TaskResumePort` adapter treating duplicate resume commands
    idempotently.

    Raises
    ------
        ValueError: If the command references an unknown checkpoint.
        TypeError: If the stored checkpoint payload cannot be deserialised into
            the expected planner-result shape.
    """
    _log_event(
        "debug",
        "generation_graph.resume.start",
        checkpoint_id=command.checkpoint_id,
    )
    checkpoint = await checkpoint_port.get(command.checkpoint_id)
    if checkpoint is None:
        _log_event(
            "error",
            "generation_graph.resume.unknown_checkpoint",
            checkpoint_id=command.checkpoint_id,
        )
        msg = f"unknown checkpoint: {command.checkpoint_id}"
        raise ValueError(msg)
    payload = checkpoint.payload
    try:
        planner_result_payload = payload["planner_result"]
    except KeyError as exc:
        msg = "checkpoint payload missing required field: planner_result"
        raise TypeError(msg) from exc
    planner_result = _planner_result_from_payload(planner_result_payload)
    if len(planner_result.plan.steps) != 1:
        msg = (
            "resume_generation_orchestration currently supports exactly one "
            "planned step per suspended checkpoint."
        )
        raise ValueError(msg)
    action_result = await resume_port.resume(command)
    result = build_generation_result(planner_result, (action_result,))
    resumed_checkpoint = await checkpoint_port.mark_resumed(checkpoint.checkpoint_id)
    _log_event(
        "debug",
        "generation_graph.resume.finish",
        checkpoint_id=resumed_checkpoint.checkpoint_id,
        idempotency_key=resumed_checkpoint.idempotency_key,
        status=resumed_checkpoint.status,
    )
    return result
