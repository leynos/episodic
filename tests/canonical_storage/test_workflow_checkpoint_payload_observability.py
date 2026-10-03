"""Observability tests for rejected persisted checkpoint payloads."""

import datetime as dt
import typing as typ
import uuid
from unittest import mock

import pytest

from episodic.canonical.domain import WorkflowCheckpointStatus
from episodic.canonical.storage import (
    SqlAlchemyWorkflowCheckpointStore,
    WorkflowCheckpointRecord,
    workflow_checkpoints,
)
from tests.canonical_storage._workflow_checkpoint_support import (
    RecordingMetrics,
    StepClock,
)

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


def _assert_payload_rejection_event(
    events: list[tuple[str, str, dict[str, object]]],
) -> None:
    """Assert the stable event shape for a rejected stored payload."""
    error_events = [event for event in events if event[0] == "error"]
    assert len(error_events) == 1, "rejected payload should emit one error event"
    level, message, fields = error_events[0]
    assert level == "error", "payload validation failures should be errors"
    assert message == "sql_checkpoint_store.checkpoint_payload_rejected", (
        "stored payload rejection should use its stable event name"
    )
    expected_fields: dict[str, object] = {
        "correlation_id": "corr-storage",
        "workflow_id": "corr-storage",
        "workflow_type": "generation_orchestration",
        "step_name": "execute",
        "action_id": "action-1",
        "failure_category": "invalid_checkpoint_payload",
    }
    assert fields == expected_fields, "rejection event should contain safe context"


@pytest.mark.asyncio
async def test_checkpoint_store_observes_rejected_persisted_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Malformed stored payloads log context and increment a bounded counter."""
    now = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
    checkpoint_id = str(uuid.uuid4())
    record = WorkflowCheckpointRecord(
        id=uuid.UUID(checkpoint_id),
        workflow_id="corr-storage",
        workflow_type="generation_orchestration",
        step_name="execute",
        idempotency_key="corr-storage:generation_orchestration:execute:action-1:0",
        payload={
            "planner_result": {
                "plan": {"steps": [{"action_id": "action-1"}]},
            },
            "invalid": object(),
        },
        status=WorkflowCheckpointStatus.SUSPENDED,
        created_at=now,
        updated_at=now,
    )
    session = mock.AsyncMock()
    session.get.return_value = record
    events: list[tuple[str, str, dict[str, object]]] = []

    def record_log_event(level: str, message: str, **fields: object) -> None:
        events.append((level, message, fields))

    monkeypatch.setattr(workflow_checkpoints, "_log_event", record_log_event)
    metrics = RecordingMetrics()
    store = SqlAlchemyWorkflowCheckpointStore(
        typ.cast("AsyncSession", session),
        metrics=metrics,
        clock=StepClock(),
    )

    with pytest.raises(TypeError) as exc_info:
        await store.get(checkpoint_id)

    assert str(exc_info.value) == "payload must be JSON-serializable.", (
        "stored payload rejection should preserve the DTO TypeError"
    )
    _assert_payload_rejection_event(events)
    assert metrics.counters == [
        (
            "workflow_checkpoint.payload_validation_failures",
            {"operation": "load", "reason": "invalid_payload"},
        ),
    ], "stored payload rejection should increment the bounded counter"
