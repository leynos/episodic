"""Tests for terminal generation-run lifecycle invariants."""

import dataclasses as dc
import datetime as dt
import uuid

import pytest

from episodic.canonical.domain import GenerationRun, GenerationRunStatus
from episodic.canonical.generation_quality import QaStatus, QualityMode

NOW = dt.datetime(2026, 6, 4, 8, 0, tzinfo=dt.UTC)


def _pending_run() -> GenerationRun:
    """Build an otherwise valid pending generation run."""
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
        quality_mode=QualityMode.DRAFT_WITHOUT_QA,
        qa_status=QaStatus.SKIPPED,
        skip_qa_rationale="No-QA vertical-slice draft.",
    )


@pytest.mark.parametrize(
    ("current_node", "ended_at", "message"),
    [
        ("complete", NOW, "terminal generation runs must not have a current node"),
        (None, None, "terminal generation runs must have an end time"),
    ],
)
def test_generation_run_rejects_invalid_terminal_lifecycle(
    current_node: str | None,
    ended_at: dt.datetime | None,
    message: str,
) -> None:
    """Terminal runs require an end time and clear their active node."""
    with pytest.raises(ValueError, match=message):
        dc.replace(
            _pending_run(),
            status=GenerationRunStatus.SUCCEEDED,
            current_node=current_node,
            ended_at=ended_at,
        )
