"""Sample entities and responses for the generation-run lifecycle steps."""

import datetime as dt
import uuid

from episodic.canonical.domain import (
    Checkpoint,
    CheckpointAction,
    CheckpointResponse,
    CheckpointStatus,
    GenerationRun,
    GenerationRunStatus,
)
from episodic.canonical.generation_quality import QaStatus, QualityMode

NOW = dt.datetime(2026, 6, 4, 8, 0, tzinfo=dt.UTC)
_ACTION_PAYLOADS: dict[str, dict[str, object]] = {
    "approve": {"approved": True},
    "request_changes": {"approved": False},
    "edit": {"approved": False},
}


def build_run() -> GenerationRun:
    """Return a sample generation run for tests."""
    return GenerationRun(
        id=uuid.uuid7(),
        episode_id=uuid.uuid7(),
        source_bundle_id=uuid.uuid7(),
        actor="editor@example.com",
        status=GenerationRunStatus.PENDING,
        current_node=None,
        budget_snapshot={},
        configuration={},
        created_at=NOW,
        updated_at=NOW,
        started_at=None,
        ended_at=None,
        error_message=None,
        quality_mode=QualityMode.DRAFT_WITHOUT_QA,
        qa_status=QaStatus.SKIPPED,
        skip_qa_rationale="No-QA vertical-slice draft.",
    )


def build_checkpoint(run_id: uuid.UUID) -> Checkpoint:
    """Return a sample checkpoint for tests."""
    return Checkpoint(
        id=uuid.uuid7(),
        generation_run_id=run_id,
        node="human_review",
        prompt="Approve the draft?",
        options=("approve", "request_changes", "edit"),
        status=CheckpointStatus.CREATED,
        created_at=NOW,
        responded_at=None,
        responded_by=None,
        response_action=None,
        response_payload={},
    )


def build_response(action: str, *, offset_minutes: int) -> CheckpointResponse:
    """Build a reviewer response for the named action."""
    return CheckpointResponse(
        action=CheckpointAction(action),
        payload=_ACTION_PAYLOADS[action],
        responded_at=NOW + dt.timedelta(minutes=offset_minutes),
        responded_by="reviewer@example.com",
    )
