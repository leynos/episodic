"""Hypothesis property-based tests for orchestration DTO payload invariants.

Issue #72 called out that the PR #69 orchestration suite had strong
deterministic unit coverage but lacked generative exploration of boundary
inputs. This module keeps checkpoint and workflow-step key properties together;
other orchestration properties live in the focused sibling modules.
"""

import hypothesis.strategies as st
import pytest
from hypothesis import given, settings

from episodic.orchestration import (
    ActionExecutionResult,
    ExecutionPlan,
    PlannerResult,
    WorkflowStepIdentity,
    build_workflow_step_idempotency_key,
)
from episodic.orchestration.langgraph import (
    _action_result_from_payload,
    _action_result_to_payload,
    _plan_from_payload,
    _plan_to_payload,
    _planner_result_from_payload,
    _planner_result_to_payload,
)
from tests._orchestration_property_support import (
    PropStepKeyInputs,
    action_result_strategy,
    execution_plan_strategy,
    planner_result_strategy,
    step_key_inputs_strategy,
)


def test_step_idempotency_key_negative_attempt_raises_value_error() -> None:
    """Negative attempts should be rejected before building a step key."""
    step = WorkflowStepIdentity(
        workflow_id="workflow-id",
        workflow_type="workflow-type",
        step_name="step-name",
        action_id="action-id",
    )

    with pytest.raises(ValueError, match="attempt must be greater than or equal"):
        build_workflow_step_idempotency_key(step, attempt=-1)


@given(
    inputs=step_key_inputs_strategy,
    attempt=st.integers(min_value=0, max_value=100),
)
@settings(max_examples=50)
def test_step_idempotency_keys_are_deterministic(
    inputs: PropStepKeyInputs,
    attempt: int,
) -> None:
    """Property test: identical workflow step inputs produce identical keys."""
    step = WorkflowStepIdentity(
        workflow_id=inputs.workflow_id,
        workflow_type=inputs.workflow_type,
        step_name=inputs.step_name,
        action_id=inputs.action_id,
    )
    first = build_workflow_step_idempotency_key(
        step,
        attempt=attempt,
    )
    second = build_workflow_step_idempotency_key(
        step,
        attempt=attempt,
    )
    assert second == first
    assert first.endswith(f":{attempt}")


@given(plan=execution_plan_strategy)
@settings(max_examples=50)
def test_execution_plan_checkpoint_payload_round_trips(
    plan: ExecutionPlan,
) -> None:
    """Property test: checkpoint plan payloads preserve execution plans."""
    assert _plan_from_payload(_plan_to_payload(plan)) == plan


@given(result=planner_result_strategy)
@settings(max_examples=50)
def test_planner_result_checkpoint_payload_round_trips(
    result: PlannerResult,
) -> None:
    """Property test: checkpoint planner payloads preserve planner results."""
    assert _planner_result_from_payload(_planner_result_to_payload(result)) == result


@given(result=action_result_strategy)
@settings(max_examples=50)
def test_action_result_checkpoint_payload_round_trips(
    result: ActionExecutionResult,
) -> None:
    """Property test: checkpoint action payloads preserve action results."""
    assert _action_result_from_payload(_action_result_to_payload(result)) == result
