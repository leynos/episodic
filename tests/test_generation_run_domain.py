"""Unit tests for generation-run domain entities.

This module covers `GenerationRun`, `GenerationEvent`, `Checkpoint`, their
status enums, and the event-sequence value constructor. The tests verify
creation invariants, validation errors for blank and non-mapping inputs,
terminal-status classification, and checkpoint state transitions. Hypothesis
properties exercise the validation rules across many generated examples, while
the `generation_run`, `generation_event`, and `checkpoint` fixtures keep valid
entity construction local and explicit.
"""

import dataclasses as dc
import datetime as dt
import uuid

import hypothesis.strategies as st
import pytest
from hypothesis import HealthCheck, given, settings

from episodic.canonical.domain import (
    Checkpoint,
    CheckpointAction,
    CheckpointResponse,
    CheckpointStatus,
    GenerationEvent,
    GenerationRun,
    GenerationRunStatus,
)
from episodic.canonical.generation_run_errors import CheckpointAlreadyTerminal
from episodic.canonical.generation_run_ports import event_seq

NOW = dt.datetime(2026, 6, 4, 8, 0, tzinfo=dt.UTC)


@pytest.fixture
def generation_run() -> GenerationRun:
    """Build a valid generation run for tests."""
    return GenerationRun(
        id=uuid.uuid7(),
        episode_id=uuid.uuid7(),
        source_bundle_id=uuid.uuid7(),
        actor="editor@example.com",
        status=GenerationRunStatus.PENDING,
        current_node=None,
        budget_snapshot={"limit": 10},
        configuration={"model": "gpt-4.1"},
        created_at=NOW,
        updated_at=NOW,
        started_at=None,
        ended_at=None,
        error_message=None,
    )


@pytest.fixture
def checkpoint(generation_run: GenerationRun) -> Checkpoint:
    """Build a valid created checkpoint for tests."""
    return Checkpoint(
        id=uuid.uuid7(),
        generation_run_id=generation_run.id,
        node="human_review",
        prompt="Approve the draft?",
        options=("approve", "request_changes"),
        status=CheckpointStatus.CREATED,
        created_at=NOW,
        responded_at=None,
        responded_by=None,
        response_action=None,
        response_payload={},
    )


def test_generation_run_status_terminal_states_are_explicit() -> None:
    """Only completed run states should be terminal."""
    assert not GenerationRunStatus.PENDING.is_terminal(), (
        "PENDING must not be terminal."
    )
    assert not GenerationRunStatus.RUNNING.is_terminal(), (
        "RUNNING must not be terminal."
    )
    assert not GenerationRunStatus.PAUSED.is_terminal(), "PAUSED must not be terminal."
    assert GenerationRunStatus.SUCCEEDED.is_terminal(), "SUCCEEDED must be terminal."
    assert GenerationRunStatus.FAILED.is_terminal(), "FAILED must be terminal."
    assert GenerationRunStatus.CANCELLED.is_terminal(), "CANCELLED must be terminal."


def test_checkpoint_status_terminal_states_are_explicit() -> None:
    """Only checkpoint end states should be terminal."""
    assert not CheckpointStatus.CREATED.is_terminal(), "CREATED must not be terminal."
    assert CheckpointStatus.RESPONDED.is_terminal(), "RESPONDED must be terminal."
    assert CheckpointStatus.TIMED_OUT.is_terminal(), "TIMED_OUT must be terminal."
    assert CheckpointStatus.CANCELLED.is_terminal(), "CANCELLED must be terminal."


def test_generation_run_rejects_blank_actor(generation_run: GenerationRun) -> None:
    """Run actors are required for auditability."""
    with pytest.raises(ValueError, match="actor"):
        dc.replace(generation_run, actor=" ")


@given(blank_actor=st.text().filter(lambda value: not value.strip()))
@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_generation_run_rejects_blank_actor_property(
    generation_run: GenerationRun,
    blank_actor: str,
) -> None:
    """Run actors reject every blank string."""
    with pytest.raises(ValueError, match="actor"):
        dc.replace(generation_run, actor=blank_actor)


def test_generation_run_rejects_non_mapping_payloads(
    generation_run: GenerationRun,
) -> None:
    """JSON mapping fields must be dictionaries at the domain boundary."""
    with pytest.raises(TypeError, match="budget_snapshot"):
        dc.replace(generation_run, budget_snapshot=[("limit", 10)])


non_mapping_values = st.one_of(
    st.lists(st.integers()),
    st.tuples(st.integers()),
    st.integers(),
    st.text(),
)


@given(bad_value=non_mapping_values)
@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_generation_run_rejects_non_mapping_payloads_property(
    generation_run: GenerationRun,
    bad_value: object,
) -> None:
    """Budget snapshots reject every non-mapping value."""
    with pytest.raises(TypeError, match="budget_snapshot"):
        dc.replace(generation_run, budget_snapshot=bad_value)


@pytest.fixture
def generation_event(generation_run: GenerationRun) -> GenerationEvent:
    """Build a valid generation event for tests."""
    return GenerationEvent(
        id=uuid.uuid7(),
        generation_run_id=generation_run.id,
        seq=event_seq(1),
        kind="node_started",
        payload={"node": "planner"},
        created_at=NOW,
        occurred_at=NOW,
    )


def test_generation_event_valid_creation(generation_event: GenerationEvent) -> None:
    """Events accept adapter-allocated positive sequences."""
    assert generation_event.seq == 1, "Valid event seq must be preserved."


def test_event_sequence_validation() -> None:
    """Event sequences must be positive."""
    with pytest.raises(ValueError, match="seq"):
        event_seq(0)


def test_event_payload_type_check(generation_event: GenerationEvent) -> None:
    """Event payloads must be mappings."""
    with pytest.raises(TypeError, match="payload"):
        dc.replace(generation_event, payload=["not", "a", "mapping"])


def test_checkpoint_response_returns_new_responded_instance(
    checkpoint: Checkpoint,
) -> None:
    """Responding to a checkpoint records reviewer action and payload."""
    responded_at = NOW + dt.timedelta(minutes=5)

    responded = checkpoint.respond(
        response=CheckpointResponse(
            action=CheckpointAction.APPROVE,
            payload={"approved": True},
            responded_at=responded_at,
            responded_by="reviewer@example.com",
        )
    )

    assert responded is not checkpoint, "Respond must return a new instance."
    assert responded.status is CheckpointStatus.RESPONDED, (
        "Status must transition to RESPONDED."
    )
    assert responded.response_action is CheckpointAction.APPROVE, (
        "Action must be recorded."
    )
    assert responded.response_payload == {"approved": True}, "Payload must be captured."
    assert responded.responded_at == responded_at, "Timestamp must be recorded."
    assert responded.responded_by == "reviewer@example.com", (
        "Reviewer must be recorded."
    )


def test_terminal_checkpoint_rejects_second_response(checkpoint: Checkpoint) -> None:
    """Terminal checkpoints must not accept repeated responses."""
    responded = checkpoint.respond(
        response=CheckpointResponse(
            action=CheckpointAction.APPROVE,
            payload={},
            responded_at=NOW,
            responded_by="reviewer@example.com",
        )
    )

    with pytest.raises(CheckpointAlreadyTerminal):
        responded.respond(
            response=CheckpointResponse(
                action=CheckpointAction.EDIT,
                payload={},
                responded_at=NOW,
                responded_by="reviewer@example.com",
            )
        )
